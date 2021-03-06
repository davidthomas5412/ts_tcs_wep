import os, unittest
import numpy as np

from scipy.ndimage.morphology import binary_opening, binary_closing, binary_erosion
from scipy.ndimage.interpolation import shift
from scipy.optimize import minimize_scalar

from lsst.ts.wep.deblend.AdapThresImage import AdapThresImage
from lsst.ts.wep.deblend.nelderMeadModify import nelderMeadModify
from lsst.ts.wep.Utility import getModulePath

from scipy.ndimage.measurements import center_of_mass

class BlendedImageDecorator(object):

    def __init__(self):

        self.__image = AdapThresImage()

    def __getattr__(self, attributeName):
        """
        
        Use the functions and attributes hold by the object.
        
        Arguments:
            attributeName {[str]} -- Name of attribute or function.
        
        Returns:
            [str] -- Returned values.
        """
        return getattr(self.__image, attributeName)

    def deblendDonut(self, iniGuessXY, magRatio):
        """
        
        Get the deblended donut image.
        
        Arguments:
            iniGuessXY {[float]} -- Initial guess of (x, y) position of neighboring star.
            magRatio {[float]} -- Initial guess of magnitude ratio between neighboring star 
                                  and bright star.
        
        Returns:
            [float] -- Deblended donut image and pixel x, y position.
        """

        # Deblended image
        imgDeblend = []

        # Postion of centroid

        # Get the initial guess of brightest donut
        realcx, realcy, realR, imgBinary = self.getCenterAndR_ef(checkEntropy=True)

        # Remove the salt and pepper noise noise of resImgBinary
        imgBinary = binary_opening(imgBinary).astype(float)
        imgBinary = binary_closing(imgBinary).astype(float)

        # Check the image quality
        if (not realcx):
            return imgDeblend, realcx, realcy

        # Get the binary image by adaptive threshold
        adapcx, adapcy, adapR, adapImgBinary = self.getCenterAndR_adap()

        # Calculate the system error by only taking the background signal
        bg1D = self.image.flatten()
        bgImgBinary1D = adapImgBinary.flatten()
        background = bg1D[bgImgBinary1D==0]
        bgPhist, pgCen = np.histogram(background, bins=256)
        sysError = pgCen[0]

        # Remove the system error
        noSysErrImage = self.image - sysError
        noSysErrImage[noSysErrImage<0] = 0

        # Get the residure map
        resImgBinary = adapImgBinary - imgBinary

        # Compensate the zero element for subtraction
        resImgBinary[np.where(resImgBinary<0)] = 0

        # Remove the salt and pepper noise noise of resImgBinary
        resImgBinary = binary_opening(resImgBinary).astype(float)

        # Calculate the shifts of x and y
        x0 = int(iniGuessXY[0] - realcx)
        y0 = int(iniGuessXY[1] - realcy)

        xoptNeighbor = nelderMeadModify(self.__funcResidue, np.array([x0, y0]), 
                                        args=(imgBinary, resImgBinary), step=15)

        # Shift the main donut image to fitted position of neighboring star 
        fitImgBinary = shift(imgBinary, [int(xoptNeighbor[0][1]), int(xoptNeighbor[0][0])])

        # Handle the numerical error of shift. Regenerate a binary image.
        fitImgBinary[fitImgBinary > 0.5] = 1
        fitImgBinary[fitImgBinary < 0.5] = 0

        # Get the overlap region between main donut and neighboring donut
        imgOverlapBinary = imgBinary + fitImgBinary
        imgOverlapBinary[imgOverlapBinary < 1.5] = 0
        imgOverlapBinary[imgOverlapBinary > 1.5] = 1

        # Get the overall binary image
        imgAllBinary = imgBinary + fitImgBinary
        imgAllBinary[imgAllBinary > 1] = 1

        # Get the reference image for the fitting
        imgRef = noSysErrImage*imgAllBinary

        # Calculate the magnitude ratio of image
        imgMainDonut = noSysErrImage*imgBinary
        imgFit = shift(imgMainDonut, [int(xoptNeighbor[0][1]), int(xoptNeighbor[0][0])])

        xoptMagNeighbor = minimize_scalar(self.__funcMag, bounds = (0, 1), method="bounded",
                                          args=(imgMainDonut, imgOverlapBinary, imgFit, imgRef, xoptNeighbor[0]))

        imgDeblend = imgMainDonut - xoptMagNeighbor.x*imgFit*imgOverlapBinary

        # Repair the boundary of image
        imgDeblend = self.__repairBoundary(imgOverlapBinary, imgBinary, imgDeblend)

        # Calculate the centroid position of donut
        realcy, realcx = center_of_mass(imgBinary)

        return imgDeblend, realcx, realcy

    def __repairBoundary(self, imgOverlapBinary, imgBinary, imgDeblend):
    	"""
    	
    	Compensate the values on boundary of overlap region between the bright star and neighboring
    	star. 
    	
    	Arguments:
    		imgOverlapBinary {[int]} -- Binary impage of overlap between bright star and neighboring
    									star.
    		imgBinary {[int]} -- Binary image of bright star.
    		imgDeblend {[float]} -- Deblended donut image.
    	
    	Returns:
    		[float] -- Repaired deblended donut image.
    	"""

    	# Copy the original data
    	repairImgDeblend = imgDeblend.copy()

    	# Get the boundary of overlap region
    	boundaryOverlap = imgOverlapBinary - binary_erosion(imgOverlapBinary)

    	# Find all boundary points
    	m, n = np.where(boundaryOverlap==1)

    	for ii in range(len(m)):

    		# Correct values that are not on the boundary next to environment
    		if (imgBinary[m[ii]-1:m[ii]+2, n[ii]-1:n[ii]+2].all()):
    			
    			# Modify the value in column
    			neighborValues = repairImgDeblend[m[ii], n[ii]-4:n[ii]+5]
    			temp = neighborValues[neighborValues!=0]
    			stdTemp = np.std(temp)
    			meanTemp = np.mean(temp)

    			for kk in range(9):
    				testValue = repairImgDeblend[m[ii], n[ii]-4+kk]
    				if (testValue != 0):
    					if (testValue >= meanTemp + 2*stdTemp) or (testValue <= meanTemp - 2*stdTemp):
    						repairImgDeblend[m[ii], n[ii]-4+kk] = (repairImgDeblend[m[ii], n[ii]-5+kk] + 
    															   repairImgDeblend[m[ii], n[ii]-3+kk])/2

    			# Modify the value in row
    			neighborValues = repairImgDeblend[m[ii]-4:m[ii]+5, n[ii]]
    			temp = neighborValues[neighborValues!=0]
    			stdTemp = np.std(temp)
    			meanTemp = np.mean(temp)

    			for kk in range(9):
    				testValue = repairImgDeblend[m[ii]-4+kk, n[ii]]
    				if (testValue != 0):
    					if (testValue >= meanTemp + 2*stdTemp) or (testValue <= meanTemp - 2*stdTemp):
    						repairImgDeblend[m[ii]-4+kk, n[ii]] = (repairImgDeblend[m[ii]-5+kk, n[ii]] + 
    															   repairImgDeblend[m[ii]-3+kk, n[ii]])/2

    	return repairImgDeblend

    def __funcMag(self, magRatio, imgMainDonut, imgOverlapBinary, imgFit, imgRef, xyShiftNeighbor):
    	"""
    	
    	Use the least square method to decide the magnitude ratio of neighboring star.
    	
    	Arguments:
    		magRatio {[float]} -- Magnitude ratio between the main star and neighboring star.
    		imgMainDonut {[float]} -- Image of the main star.
    		imgOverlapBinary {[int]} -- Binary image of overlap between the main star and neighboring star.
    		imgFit {[float]} -- Fitted image of neighboring star by the shifting of image of main star.
    		xyShiftNeighbor {[float]} -- X, Y shift from the main star to neighboring star.
    	
    	Returns:
    		[float] -- The difference between synthesized image and blended image.
    	"""

    	# Synthesize the image
    	imgNew = imgMainDonut - magRatio*imgFit*imgOverlapBinary
    	imgNew = imgNew + magRatio*shift(imgNew, [int(xyShiftNeighbor[1]), int(xyShiftNeighbor[0])])

    	# Take the least square difference 
    	delta = np.sum((imgNew-imgRef)**2)

    	return delta

    def __funcResidue(self, posShift, imgBinary, resImgBinary):
    	"""
    	
    	Use the least square method to decide the position of neighboring star.
    	
    	Arguments:
    		posShift {[float]} -- (x, y) shift from the main star position to 
    							   neighboring star.
    		imgBinary {[int]} -- Binary image of the main star.
    		resImgBinary {[int]} -- Binary image of residue of neighboring star.
    	
    	Returns:
    		[float] -- The difference between fitted binary image and residue image.
    	"""

    	# Shift the image
    	fitImgBinary = shift(imgBinary, [int(posShift[1]), int(posShift[0])])
    
    	# Handle the numerical error of shift. Regenerate a binary image.
    	fitImgBinary[fitImgBinary > 0.5] = 1
    	fitImgBinary[fitImgBinary < 0.5] = 0

    	# Take the least square difference 
    	delta = np.sum((fitImgBinary-resImgBinary)**2)

    	return delta

class BlendedImageDecoratorTest(unittest.TestCase):

    """
    Test the function of BlendedImageDecorator.
    """

    def setUp(self):

        # Get the path of module
        modulePath = getModulePath()

        # Image file
        imageFolderPath = os.path.join(modulePath, "test", "testImages", "LSST_NE_SN25")
        imageName = 'z11_0.25_intra.txt'
        imageFile = os.path.join(imageFolderPath, imageName)

        # Set the image file
        self.adapImage = AdapThresImage()
        self.adapImage.setImg(imageFile = imageFile)

        self.zeroImage = BlendedImageDecorator()
        self.zeroImage.setImg(image = np.zeros([120,120]))

        self.randImage = BlendedImageDecorator()
        self.randImage.setImg(image = np.random.rand(120,120))

    def testBlendedImage(self):

        # Generate the blended image
        image, imageMain, imageNeighbor, neighborX, neighborY = self.adapImage.generateMultiDonut(1.3, 0.1, 0.0)

        blendImage = BlendedImageDecorator()
        blendImage.setImg(image=image)

        # Do the deblending
        imgDeblend, realcx, realcy = blendImage.deblendDonut([neighborX, neighborY], 0.1)

        # Do the comparison
        delta = np.sum(np.abs(imageMain-imgDeblend))
        diffRatio = delta/np.sum(np.abs(imageMain))
        self.assertLess(diffRatio, 0.01)

        # Test the zero image that can not be pass entropy test
        imgDeblend, realcx, realcy = self.zeroImage.deblendDonut([10, 10], 0.1)
        self.assertEqual(imgDeblend, [])

        # Test the random image that can not be pass entropy test
        imgDeblend, realcx, realcy = self.randImage.deblendDonut([10, 10], 0.1)
        self.assertEqual(imgDeblend, [])

if __name__ == '__main__':

    # Do the unit test
    unittest.main()