"""
This file defines a simple operator for computing SLIC superpixels using scikit-image.
This example demonstrates how blockwise access to a 'global' operation
(such as superpixel generation) can cause undesirable results, and how
a cache can be used to force every request to be taken from a global result.
See the __main__ section, below.
It also includes a brief demonstration of lazyflow's OperatorWrapper mechanism.
"""
import numpy

import skimage.segmentation

from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.operators import OpBlockedArrayCache

class OpSlic(Operator):
    """
    Computes SLIC superpixels for any requested region of the image.
    Every request is considered independently, so it isn't desirable to
    concatenate the results of several requests into one large image.
    (If you do, the final image will appear 'quilted'.)
    """
    Input = InputSlot()
    
    # These are the slic parameters.
    # Here we give default values, but they can be changed.
    NumSegments = InputSlot(value=100)
    Compactness = InputSlot(value=0.1)
    MaxIter = InputSlot(value=10)
    
    Output = OutputSlot()
    
    def setupOutputs(self):
        self.Output.meta.assignFrom(self.Input.meta)

        tagged_shape = self.Input.meta.getTaggedShape()
        assert 'c' in tagged_shape, "We assume the image has an explicit channel axis."
        assert tagged_shape.keys()[-1] == 'c', "This code assumes that channel is the LAST axis."
        
        # Output will have exactly one channel, regardless of input channels
        tagged_shape['c'] = 1
        self.Output.meta.shape = tuple(tagged_shape.values())
    
    def execute(self, slot, subindex, roi, result):
        input_data = self.Input(roi.start, roi.stop).wait()
        print input_data.shape
        numpy.save("/tmp/image", input_data)
        slic_sp = skimage.segmentation.slic(input_data,
                                            n_segments=self.NumSegments.value,
                                            compactness=self.Compactness.value,
                                            max_iter=self.MaxIter.value,
                                            multichannel=True,
                                            enforce_connectivity=True,
                                            convert2lab=False) # Use with caution.
                                                               # This would cause slic() to have special behavior for 3-channel data,
                                                               # in which case we better really be dealing with RGB channels
                                                               # (not, say 3 unrelated image features).
        
        # slic_sp has no channel axis, so insert that axis before copying to 'result'
        result[:] = slic_sp[...,None]
        # result = slic_sp
        return result
    
    def propagateDirty(self, slot, subindex, roi):
        # For some operators, a dirty in one part of the image only causes changes in nearby regions.
        # But for superpixel operators, changes in one corner can affect results in the opposite corner.
        # Therefore, everything is dirty.
        self.Output.setDirty()

class OpSlicCached(Operator):
    """
    Computes SLIC superpixels and cache the result for the entire image.
    """
    # Same slots as OpSlic
    Input = InputSlot()
    NumSegments = InputSlot(value=200)
    Compactness = InputSlot(value=0.4)
    MaxIter = InputSlot(value=10)
    
    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super(OpSlicCached, self).__init__(*args, **kwargs)
        # This operator does no computation on its own.
        # Instead, it owns a little internal pipeline:
        # 
        # Input --> OpSlic --> OpCache --> Output
        #
        
        # Feed all inputs directly into the operator that actually computes the slic superpixels
        self.opSlic = OpSlic( parent=self )
        self.opSlic.NumSegments.connect( self.NumSegments )
        self.opSlic.Compactness.connect( self.Compactness )
        self.opSlic.MaxIter.connect( self.MaxIter )
        self.opSlic.Input.connect( self.Input )
        
        self.opCache = OpBlockedArrayCache( parent=self )
        self.opCache.Input.connect( self.opSlic.Output )
        self.Output.connect( self.opCache.Output )
    
    def setupOutputs(self):
        # The cache is capable of requesting and storing results in small blocks,
        # but we want to force the entire image to be handled and stored at once.
        # Therefore, we set the 'block shape' to be the entire image -- there will only be one block stored in the cache.
        # (Note: The OpBlockedArrayCache.innerBlockshape slot is deprecated and ignored.)
        self.opCache.outerBlockShape.setValue( self.Input.meta.shape )
    
    def execute(self, slot, subindex, roi, result):
        # When an output slot is accessed, it asks for data from it's upstream connection (if any)
        # If it has no upstream connection, then it will call it's own operator's execute() function.
        # In this case, there is only one output slot, and it already has an upstream connection.
        # Therefore, this execute() function will never be accessed -- no slots would ever call it.
        assert False, "This function will never be called."

    def propagateDirty(self, slot, subindex, roi):
        # There's nothing to do here -- our Input slot is already directly connected to a 
        # little pipeline that will propagate 'dirty notifications' all the way to the output.
        pass