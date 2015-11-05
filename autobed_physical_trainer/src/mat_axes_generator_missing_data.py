import os, sys
import operator
import numpy as np

import roslib; roslib.load_manifest('autobed_physical_trainer')
import rospy
import cPickle as pkl
from geometry_msgs.msg import TransformStamped

NUMOFTAXELS_X = 64#73 #taxels
NUMOFTAXELS_Y = 27#30 
TOTAL_TAXELS = NUMOFTAXELS_X*NUMOFTAXELS_Y

class BagfileToPickle():
    '''Converts pressure map bagfile to a pickle file with labels'''
    def __init__(self, filepath):
        filepath = filepath.rstrip('/')
        self.filename = os.path.join(filepath,'mat_axes.p')         

        rospy.init_node('mat_to_pkl', anonymous=False)
        try:
            self.mat_o = pkl.load(open(self.filename, 'rb'))
            print "Second pass. Capturing Axes"
            rospy.Subscriber("/mat_x/pose", TransformStamped,
                    self.mat_x_callback)
            rospy.Subscriber("/mat_y/pose", TransformStamped,
                    self.mat_y_callback)
            self.mat_x = []
            self.mat_y = []
            self.mat_x_captured = False
            self.mat_y_captured = False
            self.pass_number = 2
        except:
            print "First pass. Capturing origin coordinates"
            self.mat_o_captured = False
            self.mat_o = []
            rospy.Subscriber("/mat_o/pose", TransformStamped,
                    self.mat_origin_callback)
            self.pass_number = 1

        self.count = 0 #When to sample the mat_origin

    def mat_origin_callback(self, data):
        '''This callback will sample data until its asked to stop'''
        if not self.mat_o_captured:
            self.mat_o = np.array([data.transform.translation.x,
                             data.transform.translation.y,
                             data.transform.translation.z])
            self.mat_o_captured = True

    def mat_x_callback(self, data):
        '''This callback will sample data until its asked to stop'''
        if not self.mat_x_captured:
            self.mat_x = np.array([data.transform.translation.x,
                             data.transform.translation.y,
                             data.transform.translation.z])
            self.mat_x_captured = True


    def mat_y_callback(self, data):
        '''This callback will sample data until its asked to stop'''
        if not self.mat_y_captured:
            self.mat_y = np.array([data.transform.translation.x,
                             data.transform.translation.y,
                             data.transform.translation.z])
            self.mat_y_captured = True


    def run(self):
        while not rospy.is_shutdown():
            if self.pass_number == 1:
                if (self.mat_o_captured):
                    pkl.dump(self.mat_o, open(self.filename, "wb"))
                    print "Captured Mat ORIGIN Successfully. Exiting Now..."
                    sys.exit()
            elif self.pass_number == 2:
                if (self.mat_x_captured and self.mat_y_captured):
                    x_axis = np.asarray(self.mat_x) - np.asarray(self.mat_o)
                    y_axis = np.asarray(self.mat_y) - np.asarray(self.mat_o)
                    x_axis /= np.linalg.norm(x_axis)
                    y_axis /= np.linalg.norm(y_axis)
                    z_axis = np.array([0, 0, 1])
                    R_world_mat = np.concatenate((x_axis, y_axis), axis = 1)
                    R_world_mat = np.concatenate((R_world_mat, z_axis),
                                                                    axis = 1)
                    pkl.dump([self.mat_o, R_world_mat], open(self.filename, "wb"))
                    print "Captured Mat Axes Successfully. Exiting Now..."
                    sys.exit()

if __name__ == "__main__":
    '''Specify the path to the dataset. Will create a pickle file there'''
    convertor = BagfileToPickle(sys.argv[1])
    convertor.run()