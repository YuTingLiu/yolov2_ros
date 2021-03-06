#!/usr/bin/env python

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os.path
import os
import re
import sys
import tarfile
from copy import deepcopy
import numpy as np
import cv2

# ROS: includes
import rospy
from cv_bridge import CvBridge, CvBridgeError
from vision_msgs.msg import Detection2DArray, ObjectHypothesis, VisionInfo
from std_msgs.msg import Header
from sensor_msgs.msg import Image
from yolov2_ros.srv import *

class Yolov2Ros(object):
    def __init__(self):
        self.bridge = CvBridge()

        self.rgb_image_topic = rospy.get_param('~image_topic', default='/camera/rgb/image_raw')  # RGB image topic
        self.image_type = rospy.get_param('~image_type', default='rgb')  # Either 'rgb' or 'rgbd'

        rospy.loginfo('Using RGB image topic {}'.format(self.rgb_image_topic))
        rospy.loginfo('Setting image type to {}'.format(self.image_type))

        self.rgb_image_sub = rospy.Subscriber(self.rgb_image_topic, Image, self._image_cb)
        self.detect_pub = rospy.Publisher('{}/detected'.format(rospy.get_name()), Detection2DArray, queue_size=1)
        self.bounding_box_pub = rospy.Publisher('{}/bounding_box_image'.format(rospy.get_name()), Image, queue_size=1)

        if self.image_type == 'rgbd':
            self.depth_image_topic = rospy.get_param(self.depth_image_topic, default='/camera/depth_registered/image_raw')
            rospy.loginfo('Using depth image topic {}'.format(self.depth_image_topic))

            self.depth_image_sub = rospy.Subscriber(self.depth_topic, Image, self._depth_cb)

        # rate = rospy.Rate(30)
        self.rgb_image = Image()
        self.depth_image = Image()
        
        last_image = Image()
        while not rospy.is_shutdown():
            cur_img = self.rgb_image
            cur_depth = self.depth_image
            if cur_img.header.stamp != last_image.header.stamp:
                rospy.wait_for_service('yolo_detect')
                try:
                    yolo_detect = rospy.ServiceProxy('yolo_detect', YoloDetect, persistent=True)
                    detected = yolo_detect(YoloDetectRequest(cur_img)).detection
                    
                    try:
                        cv_image = self.bridge.imgmsg_to_cv2(cur_img, "bgr8")
                        # cv_depth_image = self.bridge.imgmsg_to_cv2(cur_img, "16UC1")
                    except CvBridgeError as e:
                        rospy.logerr(e)
                    
                    if len(detected.detections) > 0:
                        # rospy.loginfo('Found {} bounding boxes'.format(len(detected.detection.detections)))
                        if self.image_type == 'rgbd':
                            for i in range(0,len(detected.detections)):
                                detected.detections[i].source_img = cur_depth
                        else:
                            for i in range(0,len(detected.detections)):
                                detected.detections[i].source_img = cur_img
                        self.detect_pub.publish(detected)
                    
                    image = self._draw_boxes(cv_image, detected)
                    self.bounding_box_pub.publish(self.bridge.cv2_to_imgmsg(image, "bgr8"))
                except rospy.ServiceException as e:
                    rospy.logerr(e)
            
            last_image = cur_img
            # rate.sleep()
    
    def _image_cb(self, data):
        self.rgb_image = data

    def _depth_cb(self, data):
        self.depth_image = data

    def _draw_boxes(self, image, detected):
        for detect in detected.detections:
            box = detect.bbox
            xmin = int(box.center.x - (box.size_x/2))
            xmax = int(box.center.x + (box.size_x/2))
            ymin = int(box.center.y - (box.size_y/2))
            ymax = int(box.center.y + (box.size_y/2))

            cv2.rectangle(image, (xmin,ymin), (xmax,ymax), (0,255,0), 3)
            cv2.putText(image, 
                        str(detect.results[0].score), 
                        (xmin, ymin - 13), 
                        cv2.FONT_HERSHEY_SIMPLEX, 
                        1e-3 * image.shape[0], 
                        (0,255,0), 2)

        return image
    
    # TODO: Implement
    def calculate_distance(self, depth_map, detected):
        # Only publish if you see an object and the closest
        # Loop through all the bounding boxes and find min
        object_depth = sys.maxsize
        detected = False
        #bounding_box = None
        for i in range(len(results)):
            # check for objects pre-defined in mocap
            current_feat = results[i][0]
            detected = True
            location = self.get_object_2dlocation(i, results)
            #x = location[0]
            #y = location[1]
            w = location[2]
            h = location[3]
            x_center = location[4]
            y_center = location[5]

            center_pixel_depth = image_depth[y_center, x_center]
            distance_avg = self.depth_region(
                image_depth, y_center, x_center, w, h)
            # convert to mm
            distance = float(center_pixel_depth) * 0.001
            # print("Distance of object {} from target : \
            #      {}".format(i, distance))

            # print("Averaged distance of object {} : "
            #      .format(distance_avg))

            # self.draw_bounding_box(results, i)
            if distance < object_depth:
                object_depth = distance_avg
                #bounding_box = [x, y, w, h]
                object_name = results[i][0]

        if(detected):
            # Publish the distance and bounding box
            object_loc = [x_center, y_center]
            measurements = self.calculate_bearing(object_loc, object_depth)

            bearing = measurements[0]
            object_range = measurements[1]

            object_topic = self.construct_topic(
                            object_depth,
                            x_center,
                            y_center,
                            bearing,
                            object_range,
                            object_name)

            # rospy.loginfo(self.pub_img_pos)
            self.pub_img_pos.publish(object_topic)

    def depth_region(self, depth_map, detection):
        # grab depths along a strip and take average
        # go half way
        box = detection.bbox

        y_center = box.center.y
        x_center = box.center.x
        w = box.size_x
        h = box.size_y

        starting_width = w/4
        end_width = w - starting_width
        x_center = x_center - starting_width
        pixie_avg = 0.0

        for i in range(starting_width, end_width):
            assert (depth_map.shape[1] > end_width)
            assert (depth_map.shape[1] > x_center)
            pixel_depth = depth_map[y_center, x_center]
            pixie_avg += pixel_depth
            x_center += 1

        pixie_avg = (pixie_avg/(end_width - starting_width))
        return float(pixie_avg)

    # TODO: Implement
    def calculate_bearing(self, object_loc, object_depth):
        # only consider horizontal FOV.
        # Bearing is only in 2D
        horiz_fov = 57.0  # degrees

        # Define Kinect image params
        image_width = 640  # Pixels

        # Calculate Horizontal Resolution
        horiz_res = horiz_fov/image_width

        # location of object in pixels.
        # Measured from center of image.
        # Positive x is to the left, positive y is upwards
        obj_x = image_width/2.0 - object_loc[0]

        # Calculate angle of object in relation to center of image
        bearing = obj_x*horiz_res        # degrees
        bearing = bearing*math.pi/180.0  # radians

        # Calculate true range, using measured bearing value.
        # Defined as depth divided by cosine of bearing angle
        if np.cos(bearing) != 0.0:
            object_range = object_depth/np.cos(bearing)
        else:
            object_range = object_depth

        measurements = [bearing, object_range]

        return measurements

if __name__ == '__main__':
    rospy.init_node('yolov2_ros')

    try:
        yr = Yolov2Ros()
    except rospy.ROSInterruptException:
        pass

