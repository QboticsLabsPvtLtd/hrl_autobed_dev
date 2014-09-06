#!/usr/bin/env python

import sys
import serial
import numpy as np

import roslib; roslib.load_manifest('hrl_autobed_dev')
import rospy, rosparam
import serial_driver
import sharp_prox_driver

from std_msgs.msg import Float32 
from geometry_msgs.msg import Transform, Vector3, Quaternion

from m3skin_ros.srv import None_TransformArray, None_TransformArrayResponse
from m3skin_ros.srv import None_String, None_StringResponse

from numpy import sin, linspace, pi
from pylab import plot, show, title, xlabel, ylabel, subplot
from scipy import fft, arange

"""This is the maximum error allowed in our control system."""
ERROR_OFFSET = [100, 4, 100]#centimeters, degrees , degrees
"""List of positive movements"""
AUTOBED_COMMANDS = [[0, 'A', 'B'], [0, 'C', 'D'], [0, 'E', 'F']]
"""Number of Actuators"""
NUM_ACTUATORS = 3
""" Input to the control system."""
autobed_u = np.zeros(NUM_ACTUATORS) 


def autobed_engine_callback(data):
    ''' Accepts incoming position values from the base selection algorithm and assigns it to a
    global variable. This variable is then used to guide the autobed to the desired position 
    using the engine'''
    autobed_u = np.asarray(data.data)
   


def autobed_engine():
    '''Autobed engine node that listens into the base selection output data array
    and feeds the same as an input to the autobed control system. Further, it listens to the sensor
    position'''
    #baudrate = sys.argv[3]
    #Initialize listener node to hear command
    rospy.init_node('autobed_engine', anonymous = True)
    #Sends a serial command to the Autobed
    autobed_sender = serial.Serial('/dev/ttyUSB0', baudrate = baudrate)
    #Create a proximity sensor object 
    prox_driver = sharp_prox_driver.ProximitySensorDriver(NUM_ACTUATORS, param_file = sys.argv[2], dev = sys.argv[1], baudrate)
    
    while not rospy.is_shutdown():
        #Start a subscriber to run the autobed engine when we get a command
        rospy.Subscriber("/abdin0/data", Float32, autobed_engine_callback)
    
        #Compute error vector
        autobed_error = np.asarray(autobed_u - (prox_driver.get_sensor_data()[-1])[:NUM_ACTUATORS])
        #Zero the error if its too small
        autobed_error[np.absolute(autobed_error) < ERROR_OFFSET] = 0 
             
        for i in range(NUM_ACTUATORS):
            if abs(autobed_error[i]) > 0.0:
                autobed_sender.write(AUTOBED_COMMANDS[i][int(autobed_error[i]/abs(autobed_error[i]))]) 
        
        rospy.spin()




if __name__ == "__main__":
    autobed_engine()

