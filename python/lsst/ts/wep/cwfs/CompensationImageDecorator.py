import os, re, sys, unittest
import numpy as np

from scipy.ndimage import generate_binary_structure, iterate_structure
from scipy.ndimage.morphology import binary_dilation, binary_erosion
from scipy.interpolate import RectBivariateSpline

from lsst.ts.wep.cwfs.Tool import padArray, extractArray, ZernikeAnnularGrad, ZernikeAnnularJacobian
from lsst.ts.wep.cwfs.lib.cyMath import poly10_2D, poly10Grad
from lsst.ts.wep.cwfs.Image import Image
from lsst.ts.wep.cwfs.Instrument import Instrument
from lsst.ts.wep.Utility import getModulePath

class CompensationImageDecorator(object):

    # Constant
    INTRA = "intra"
    EXTRA = "extra"

    def __init__(self):
        """
        
        Instantiate the class of CompensationImageDecorator.
        """

        self.__image = None

        # Parameters used for transport of intensity equation (TIE)
        self.sizeinPix = None
        self.fieldX = None
        self.fieldY = None
        self.image0 = None
        self.fldr = None
        self.atype = None
        self.offAxis_coeff = None
        self.offAxisOffset = None
        self.caustic = False

        self.pMask = None
        self.cMask = None

    def __getattr__(self, attributeName):
        """
        
        Use the functions and attributes hold by the object.
        
        Arguments:
            attributeName {[str]} -- Name of attribute or function.
        
        Returns:
            [str] -- Returned values.
        """
        return getattr(self.__image, attributeName)

    def setImg(self, fieldXY, image=None, imageFile=None, atype=None):
        """
        
        Set the wavefront image.
        
        Arguments:
            fieldXY {[float]} -- Position of donut on the focal plane in degree.
        
        Keyword Arguments:
            image {[float]} -- Array of image. (default: {None})
            imageFile {[string]} -- Path of image file. (default: {None})
            atype {[string]} -- Type of image. It should be "intra" or "extra". (default: {None})
        
        Raises:
            TypeError -- Error if the atype is not "intra" or "extra". 
        """

        # Instantiate the image object
        self.__image = Image()

        # Read the file if there is no input image
        self.__image.setImg(image=image, imageFile=imageFile)

        # Make sure the image size is n by n
        if (self.__image.image.shape[0] != self.__image.image.shape[1]):
            raise RuntimeError("Only square image stamps are accepted.")
        elif (self.__image.image.shape[0] % 2 == 1):
            raise RuntimeError("Number of pixels cannot be odd numbers.")

        # Dimension of image
        self.sizeinPix = self.__image.image.shape[0]

        # Donut position in degree
        self.fieldX, self.fieldY = fieldXY

        # Save the initial image if we want the compensator always start from this
        self.image0 = None

        # We will need self.fldr to be on denominator
        self.fldr = np.max((np.hypot(self.fieldX, self.fieldY), 1e-8))        

        # Check the type of image
        if atype.lower() not in (self.INTRA, self.EXTRA):
            raise TypeError("Image defocal type must be 'intra' or 'extra'.")
        self.atype = atype

        # Coefficient to do the off-axis correction
        self.offAxis_coeff = None

        # Defocal distance (Baseline is 1.5mm. The configuration file now is 1mm.)
        self.offAxisOffset = 0

        # Check the image has the problem or not
        self.caustic = False

        # Reset all mask related parameters
        self.pMask = None
        self.cMask = None

    def updateImage0(self):
        """
        
        Update the backup of initial image. This will be used in the outer loop iteration, which
        always uses the initial image (image0) before each iteration starts.
        """

        # Update the initial image for future use
        self.image0 = self.__image.image.copy()

    def imageCoCenter(self, inst, fov=3.5, debugLevel=0):
        """
        
        Shift the weighting center of donut to the center of reference image with the correction of 
        projection of fieldX and fieldY.

        Arguments:
            inst {[Instrument]} -- Instrument to use.
        
        Keyword Arguments:
            fov {[float]} -- Field of view (FOV) of telescope. (default: {3.5})
            debugLevel {[int]} -- Show the information under the running. If the value is higher, 
                                the information shows more. It can be 0, 1, 2, or 3. (default: {0})
        """

        # Calculate the weighting center (x, y) and radius
        x1, y1 = self.getCenterAndR_ef()[0:2]

        # Show the co-center information
        if (debugLevel >= 3):
            print("imageCoCenter: (x, y) = (%8.2f,%8.2f)\n" % (x1, y1))

        # Calculate the center position on image
        # 0.5 is the half of 1 pixel
        sensorSamples = inst.parameter["sensorSamples"]
        stampCenterx1 = sensorSamples/2. + 0.5
        stampCentery1 = sensorSamples/2. + 0.5

        # Shift in the radial direction
        # The field of view (FOV) of LSST camera is 3.5 degree
        offset = inst.parameter["offset"]
        pixelSize = inst.parameter["pixelSize"]
        radialShift = fov*(offset/1e-3)*(10e-6/pixelSize)

        # Calculate the projection of distance of donut to center
        radialShift = radialShift*(self.fldr/(fov/2))

        # Do not consider the condition out of FOV of lsst
        if (self.fldr > (fov/2)):
            radialShift = 0

        # Calculate the cos(theta) for projection
        I1c = self.fieldX/self.fldr

        # Calculate the sin(theta) for projection
        I1s = self.fieldY/self.fldr

        # Get the projected x, y-coordinate
        stampCenterx1 = stampCenterx1 + radialShift*I1c
        stampCentery1 = stampCentery1 + radialShift*I1s

        # Shift the image to the projected position
        self.__image.updateImage(np.roll(self.__image.image, int(np.round(stampCentery1 - y1)), axis=0))
        self.__image.updateImage(np.roll(self.__image.image, int(np.round(stampCenterx1 - x1)), axis=1))

    def compensate(self, inst, algo, zcCol, model):
        """
        
        Calculate the image compensated from the affection of wavefront.
        
        Arguments:
            inst {[Instrument]} -- Instrument to use.
            algo {[Algorithm]} -- Algorithm to solve the Poisson's equation. It can by done 
                                  by the fast Fourier transform or serial expansion.
            zcCol {[float]} -- Coefficients of wavefront.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
        
        Raises:
            Exception -- Number of terms of normal/ annular Zernike polynomilas does 
                         not match the needed number for compensation to use.
        """

        # Check the condition of inputs
        numTerms = algo.parameter["numTerms"]
        if ((zcCol.ndim == 1) and (len(zcCol) != numTerms)):
            raise RuntimeError("input:size", 
                "zcCol in compensate needs to be a %d row column vector. \n" % numTerms)

        # Dimension of image
        sm, sn = self.__image.image.shape

        # Dimenstion of projected image on focal plane 
        projSamples = sm

        # Let us create a look-up table for x -> xp first. 
        luty, lutx = np.mgrid[-(projSamples/2 - 0.5):(projSamples/2 + 0.5), 
                              -(projSamples/2 - 0.5):(projSamples/2 + 0.5)]

        sensorFactor = inst.parameter["sensorFactor"]
        lutx = lutx/(projSamples/2/sensorFactor)
        luty = luty/(projSamples/2/sensorFactor)

        # Set up the mapping
        lutxp, lutyp, J = self.__aperture2image(inst, algo, zcCol, lutx, luty, 
                                                projSamples, model)

        show_lutxyp = self.__showProjection(lutxp, lutyp, sensorFactor, 
                                            projSamples, raytrace=False)
        if (np.all(show_lutxyp <= 0)):
            self.caustic = True
            return

        # Calculate the weighting center (x, y) and radius
        realcx, realcy = self.__image.getCenterAndR_ef()[0:2]

        # Extend the dimension of image by 20 pixel in x and y direction
        show_lutxyp = padArray(show_lutxyp, projSamples+20)

        # Get the binary matrix of image on pupil plane if raytrace=False
        struct0 = generate_binary_structure(2, 1)
        struct = iterate_structure(struct0, 4)
        struct = binary_dilation(struct, structure=struct0, iterations=2).astype(int)
        show_lutxyp = binary_dilation(show_lutxyp, structure=struct)
        show_lutxyp = binary_erosion(show_lutxyp, structure=struct)

        # Extract the region from the center of image and get the original one
        show_lutxyp = extractArray(show_lutxyp, projSamples)

        # Calculate the weighting center (x, y) and radius
        projcx, projcy = self.__image.getCenterAndR_ef(image=show_lutxyp.astype(float))[0:2]

        # Shift the image to center of projection on pupil
        # +(-) means we need to move image to the right (left)
        shiftx = projcx - realcx
        # +(-) means we need to move image upward (downward)
        shifty = projcy - realcy
        
        self.__image.image = np.roll(self.__image.image, int(np.round(shifty)), axis=0)
        self.__image.image = np.roll(self.__image.image, int(np.round(shiftx)), axis=1)

        # Construct the interpolant to get the intensity on (x', p') plane
        # that corresponds to the grid points on (x,y)
        yp, xp = np.mgrid[-(sm/2 - 0.5):(sm/2 + 0.5), -(sm/2 - 0.5):(sm/2 + 0.5)]

        xp = xp/(sm/2/sensorFactor)
        yp = yp/(sm/2/sensorFactor)

        # Put the NaN to be 0 for the interpolate to use
        lutxp[np.isnan(lutxp)] = 0
        lutyp[np.isnan(lutyp)] = 0

        # Construct the function for interpolation
        ip = RectBivariateSpline(yp[:, 0], xp[0, :], self.__image.image, kx=1, ky=1)

        # Construct the projected image by the interpolation
        lutIp = np.zeros(lutxp.shape[0]*lutxp.shape[1])
        for ii, (xx, yy) in enumerate(zip(lutxp.ravel(), lutyp.ravel())):
            lutIp[ii] = ip(yy, xx)
        lutIp = lutIp.reshape(lutxp.shape)

        # Calaculate the image on focal plane with compensation based on flux conservation
        # I(x, y)/I'(x', y') = J = (dx'/dx)*(dy'/dy) - (dx'/dy)*(dy'/dx) 
        self.__image.image = lutIp*J

        if (self.atype == "extra"):
            self.__image.image = np.rot90(self.__image.image, k=2)

        # Put NaN to be 0
        self.__image.image[np.isnan(self.__image.image)] = 0

        # Check the compensated image has the problem or not.
        # The negative value means the over-compensation from wavefront error
        if (np.any(self.__image.image < 0) and np.all(self.image0 >= 0)):
            print("WARNING: negative scale parameter, image is within caustic, zcCol (in um)=\n")
            self.caustic = True

        # Put the overcompensated part to be 0.
        self.__image.image[self.__image.image < 0] = 0

    def __aperture2image(self, inst, algo, zcCol, lutx, luty, projSamples, model):
        """
        
        Calculate the x, y-coordinate on the focal plane and the related Jacobian matrix.
        
        Arguments:
            inst {[Instrument]} -- Instrument to use.
            algo {[Algorithm]} -- Algorithm to solve the Poisson's equation. It can by done 
                                  by the fast Fourier transform or serial expansion.
            zcCol {[float]} -- Coefficients of optical basis. It is Zernike polynomials in the 
                               baseline.
            lutx {[float]} -- x-coordinate on pupil plane.
            luty {[float]} -- y-coordinate on pupil plane.
            projSamples {[int]} -- Dimension of projected image. This value considers the
                                   magnification ratio of donut image.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
        
        Returns:
            [float] -- x, y-coordinate on the focal plane.
            [float] -- Jacobian matrix between the pupil and focal plane.
        """

        # Get the radius: R = D/2    
        R = inst.parameter["apertureDiameter"]/2.0

        # Calculate C = -f(f-l)/l/R^2. This is for the calculation of reduced coordinate.
        if (self.atype == self.INTRA):
            l = inst.parameter["offset"]
        elif (self.atype == self.EXTRA):
            l = -inst.parameter["offset"]
        focalLength = inst.parameter["focalLength"]
        myC = -focalLength*(focalLength - l)/l/R**2

        # Get the functions to do the off-axis correction by numerical fitting
        # Order to do the off-axis correction. The order is 10 now.
        offAxisPolyOrder = algo.parameter["offAxisPolyOrder"]
        polyFunc = self.__getFunction("poly%d_2D" % offAxisPolyOrder)
        polyGradFunc = self.__getFunction("poly%dGrad" % offAxisPolyOrder)
    
        # Calculate the distance to center
        lutr = np.sqrt(lutx**2 + luty**2)

        # Calculated the extended ring radius (delta r), which is to extended the available 
        # pupil area.
        # 1 pixel larger than projected pupil. No need to be EF-like, anything
        # outside of this will be masked off by the computational mask
        sensorFactor = inst.parameter["sensorFactor"]
        onepixel = 1/(projSamples/2/sensorFactor)

        # Get the index that the point is out of the range of extended pupil
        obscuration = inst.parameter["obscuration"]
        idxout = (lutr > 1+onepixel)|(lutr < obscuration-onepixel)

        # Define the element to be NaN if it is out of range
        lutx[idxout] = np.nan
        luty[idxout] = np.nan

        # Get the index in the extended area of outer boundary with the width of onepixel
        idxbound = (lutr <= 1+onepixel)&(lutr > 1)

        # Calculate the extended x, y-coordinate (x' = x/r*r', r'=1)
        lutx[idxbound] = lutx[idxbound]/lutr[idxbound]
        luty[idxbound] = luty[idxbound]/lutr[idxbound]

        # Get the index in the extended area of inner boundary with the width of onepixel
        idxinbd = (lutr < obscuration)&(lutr > obscuration-onepixel)
        
        # Calculate the extended x, y-coordinate (x' = x/r*r', r'=obscuration)
        lutx[idxinbd] = lutx[idxinbd]/lutr[idxinbd]*obscuration
        luty[idxinbd] = luty[idxinbd]/lutr[idxinbd]*obscuration
    
        # Get the corrected x, y-coordinate on focal plane (lutxp, lutyp)
        if (model == "paraxial"):
            # No correction is needed in "paraxial" model
            lutxp = lutx
            lutyp = luty

        elif (model == "onAxis"):
    
            # Calculate F(x, y) = m * sqrt(f^2-R^2) / sqrt(f^2-(x^2+y^2)*R^2)
            # m is the mask scaling factor
            myA2 = (focalLength**2 - R**2) / (focalLength**2 - lutr**2 * R**2)

            # Put the unphysical value as NaN
            myA = myA2.copy()
            idx = (myA < 0)
            myA[idx] = np.nan
            myA[~idx] = np.sqrt(myA2[~idx])

            # Mask scaling factor (for fast beam) 
            maskScalingFactor = algo.parameter["maskScalingFactor"]

            # Calculate the x, y-coordinate on focal plane
            # x' = F(x,y)*x + C*(dW/dx), y' = F(x,y)*y + C*(dW/dy) 
            lutxp = maskScalingFactor*myA*lutx
            lutyp = maskScalingFactor*myA*luty

        elif (model == "offAxis"):

            # Get the coefficient of polynomials for off-axis correction
            tt = self.offAxisOffset

            cx = (self.offAxis_coeff[0, :] - self.offAxis_coeff[2, :]) * (tt+l)/(2*tt) + \
                    self.offAxis_coeff[2, :]
            cy = (self.offAxis_coeff[1, :] - self.offAxis_coeff[3, :]) * (tt+l)/(2*tt) + \
                    self.offAxis_coeff[3, :]

            # This will be inverted back by typesign later on.
            # We do the inversion here to make the (x,y)->(x',y') equations has
            # the same form as the paraxial case.
            cx = np.sign(l)*cx
            cy = np.sign(l)*cy

            # Do the orthogonalization: x'=1/sqrt(2)*(x+y), y'=1/sqrt(2)*(x-y)
            # Calculate the rotation angle for the orthogonalization
            costheta = (self.fieldX + self.fieldY)/self.fldr/np.sqrt(2)
            if (costheta > 1):
                costheta = 1
            elif (costheta < -1):
                costheta = -1
    
            sintheta = np.sqrt(1 - costheta**2)
            if (self.fieldY < self.fieldX):
                sintheta = -sintheta
    
            # Create the pupil grid in off-axis model. This gives the x,y-coordinate 
            # in the extended ring area defined by the parameter of onepixel.

            # Get the mask-related parameters
            maskCa, maskRa, maskCb, maskRb = self.__interpMaskParam(self.fieldX, 
                                                        self.fieldY, inst.maskParam)

            lutx, luty = self.__createPupilGrid(lutx, luty, onepixel, maskCa, 
                                maskCb, maskRa, maskRb, self.fieldX, self.fieldY)

            # Calculate the x, y-coordinate on focal plane

            # First rotate back to reference orientation
            lutx0 = lutx*costheta + luty*sintheta
            luty0 = -lutx*sintheta + luty*costheta

            # Use the mapping at reference orientation
            lutxp0 = polyFunc(cx, lutx0, y=luty0)
            lutyp0 = polyFunc(cy, lutx0, y=luty0)
            
            # Rotate back to focal plane
            lutxp = lutxp0*costheta - lutyp0*sintheta  
            lutyp = lutxp0*sintheta + lutyp0*costheta

            # Zemax data are in mm, therefore 1000
            sensorSamples = inst.parameter["sensorSamples"]
            pixelSize = inst.parameter["pixelSize"]
            reduced_coordi_factor = 1e-3/(sensorSamples/2*pixelSize/sensorFactor)

            # Reduced coordinates, so that this can be added with the dW/dz
            lutxp = lutxp*reduced_coordi_factor
            lutyp = lutyp*reduced_coordi_factor

        else:
            print('Wrong optical model type in compensate. \n')
            return
    
        # Obscuration of annular aperture
        zobsR = algo.parameter["zobsR"]

        # Calculate the x, y-coordinate on focal plane
        # x' = F(x,y)*x + C*(dW/dx), y' = F(x,y)*y + C*(dW/dy)

        # In Model basis (zer: Zernike polynomials)
        if (zcCol.ndim == 1):
            lutxp = lutxp + myC*ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dx")
            lutyp = lutyp + myC*ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dy")
    
        # Make the sign to be consistent
        if (self.atype == "extra"):
            lutxp = -lutxp
            lutyp = -lutyp
    
        # Calculate the Jacobian matrix
        # In Model basis (zer: Zernike polynomials)
        if (zcCol.ndim == 1):
            if (model == "paraxial"):
                J = 1 + myC * ZernikeAnnularJacobian(zcCol, lutx, luty, zobsR, "1st") + \
                    myC**2 * ZernikeAnnularJacobian(zcCol, lutx, luty, zobsR, "2nd")    
            
            elif (model == "onAxis"):
                xpox = maskScalingFactor * myA * (1 + \
                    lutx**2 * R**2. / (focalLength**2 - R**2 * lutr**2)) + \
                    myC * ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dx2")
                
                ypoy = maskScalingFactor * myA * (1 + \
                    luty**2 * R**2. / (focalLength**2 - R**2 * lutr**2)) + \
                    myC * ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dy2")

                xpoy = maskScalingFactor * myA * \
                    lutx * luty * R**2 / (focalLength**2 - R**2 * lutr**2) + \
                    myC * ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dxy")

                ypox = xpoy
    
                J = xpox*ypoy - xpoy*ypox

            elif (model == "offAxis"):
                xp0ox = polyGradFunc(cx, lutx0, luty0, "dx") * costheta - \
                        polyGradFunc(cx, lutx0, luty0, "dy") * sintheta
                
                yp0ox = polyGradFunc(cy, lutx0, luty0, "dx") * costheta - \
                        polyGradFunc(cy, lutx0, luty0, "dy") * sintheta
                
                xp0oy = polyGradFunc(cx, lutx0, luty0, "dx") * sintheta + \
                        polyGradFunc(cx, lutx0, luty0, "dy") * costheta
                
                yp0oy = polyGradFunc(cy, lutx0, luty0, "dx") * sintheta + \
                        polyGradFunc(cy, lutx0, luty0, "dy") * costheta
                
                xpox = (xp0ox*costheta - yp0ox*sintheta)*reduced_coordi_factor + \
                        myC*ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dx2")
    
                ypoy = (xp0oy*sintheta + yp0oy*costheta)*reduced_coordi_factor + \
                        myC*ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dy2")
    
                temp = myC*ZernikeAnnularGrad(zcCol, lutx, luty, zobsR, "dxy")

                # if temp==0,xpoy doesn't need to be symmetric about x=y
                xpoy = (xp0oy*costheta - yp0oy*sintheta)*reduced_coordi_factor + temp

                # xpoy-flipud(rot90(ypox))==0 is true
                ypox = (xp0ox*sintheta + yp0ox*costheta)*reduced_coordi_factor + temp

                J = xpox*ypoy - xpoy*ypox
    
        return lutxp, lutyp, J

    def __getFunction(self, name):
        """
        
        Decide to call the function of __poly10_2D() or __poly10Grad(). This is to correct 
        the off-axis distortion. A numerical solution with 2-dimensions 10 order polynomials 
        to map between the telescope aperature and defocused image plane is used.
        
        Arguments:
            name {[string]} -- Function name to call.
        
        Returns:
            [float] -- Corrected image after the correction.
        
        Raises:
            RuntimeError -- Raise error if the function name does not exist.
        """

        # Construnct the dictionary table for calling function.
        # The reason to use the dictionary is for the future's extension.
        funcTable = dict(poly10_2D = self.__poly10_2D,
                         poly10Grad = self.__poly10Grad)

        # Look for the function to call
        if name in funcTable:
            return funcTable[name]
    
        # Error for unknown function name
        raise RuntimeError("Unknown function name: %s" % name)

    def __poly10_2D(self, c, data, y=None):
        """
        
        Correct the off-axis distortion by fitting with a 10 order polynomial 
        equation. 
        
        Arguments:
            c {[float]} -- Parameters of off-axis distrotion.
            data {[float]} -- x, y-coordinate on aperature. If y is provided, 
                              this will be just the x-coordinate.
        
        Keyword Arguments:
            y {[float]} -- y-coordinate at aperature (default: {None}).
        
        Returns:
            [float] -- Corrected parameters for off-axis distortion.
        """

        # Decide the x, y-coordinate data on aperature
        if (y is None):
            x = data[0, :]
            y = data[1, :]
        else:
            x = data
    
        # Correct the off-axis distortion
        return poly10_2D(c, x.flatten(), y.flatten()).reshape(x.shape)
    
    def __poly10Grad(self, c, x, y, atype):
        """
        
        Correct the off-axis distortion by fitting with a 10 order polynomial 
        equation in the gradident part. 
        
        Arguments:
            c {[float]} -- Parameters of off-axis distrotion.
            x {[type]} -- x-coordinate at aperature.
            y {[float]} -- y-coordinate at aperature.
            atype {[string]} -- Direction of gradient. It can be "dx" or "dy".
        
        Returns:
            [float] -- Corrected parameters for off-axis distortion.
        """
        
        return poly10Grad(c, x.flatten(), y.flatten(), atype).reshape(x.shape)

    def __createPupilGrid(self, lutx, luty, onepixel, ca, cb, ra, rb, fieldX, fieldY=None):
        """
        
        Create the pupil grid in off-axis model. This function gives the x,y-coordinate in the 
        extended ring area defined by the parameter of onepixel.

        Arguments:
            lutx {[float]} -- x-coordinate on pupil plane.
            luty {[float]} -- y-coordinate on pupil plane.
            onepixel {[float]} -- Exteneded delta radius.
            ca {[float]} -- Center of outer ring on the pupil plane.
            cb {float} -- Center of inner ring on the pupil plane.
            ra {[float]} -- Radius of outer ring on the pupil plane.
            rb {[float]} -- Radius of inner ring on the pupil plane.
            fieldX {[float]} -- x-coordinate of donut on the focal plane in degree.
                                If only fieldX is given, this will be fldr = sqrt(2)*fieldX
                                actually.
        
        Keyword Arguments:
            fieldY {[float]} -- y-coordinate of donut on the focal plane in degree. (default: {None})
        
        Returns:
            [float] -- x, y-coordinate of extended ring area on pupil plane.
        """

        # Calculate fieldX, fieldY if only input of fieldX (= fldr = sqrt(2)*fieldX actually) 
        # is provided
        if (fieldY is None):
            # Input of filedX is fldr actually
            fldr = fieldX
            # Divide fldr by sqrt(2) to get fieldX = fieldY
            fieldX = fldr/np.sqrt(2)
            fieldY = fieldX
    
        # Rotate the mask center after the off-axis correction based on the position 
        # of fieldX and fieldY
        cax, cay, cbx, cby = self.__rotateMaskParam(ca, cb, fieldX, fieldY)
    
        # Get x, y coordinate of extended outer boundary by the linear approximation
        lutx, luty = self.__approximateExtendedXY(lutx, luty, cax, cay, ra, ra+onepixel, "outer")

        # Get x, y coordinate of extended inner boundary by the linear approximation
        lutx, luty = self.__approximateExtendedXY(lutx, luty, cbx, cby, rb-onepixel, rb, "inner")      
    
        return lutx, luty

    def __approximateExtendedXY(self, lutx, luty, cenX, cenY, innerR, outerR, config):
        """
        
        Calculate the x, y-cooridnate on puil plane in the extended ring area by the linear
        approxination, which is used in the off-axis correction. 
        
        Arguments:
            lutx {[float]} -- x-coordinate on pupil plane.
            luty {[float]} -- y-coordinate on pupil plane.
            cenX {[float]} -- x-coordinate of boundary ring center.
            cenY {[float]} -- y-coordinate of boundary ring center.
            innerR {[float]} -- Inner radius of extended ring.
            outerR {[float]} -- Outer radius of extended ring.
            config {[string]} -- Configuration to calculate the x,y-coordinate in the extended ring.
                                 "inner": inner extended ring; 
                                 "outer": outer extended ring.
        
        Returns:
            [float] -- x, y-coordinate of extended ring area on pupil plane.
        """

        # Catculate the distance to rotated center of boundary ring
        lutr = np.sqrt((lutx - cenX)**2 + (luty - cenY)**2)

        # Define NaN to be 999 for the comparison in the following step
        tmp = lutr.copy()
        tmp[np.isnan(tmp)] = 999

        # Get the available index that the related distance is between innderR and outerR
        idxbound = (~np.isnan(lutr)) & (tmp >= innerR ) & (tmp <= outerR)

        # Deside R based on the configuration
        if (config == "outer"):
            R = innerR
            # Get the index that the related distance is bigger than outerR
            idxout = (tmp > outerR)
        elif (config == "inner"):
            R = outerR
            # Get the index that the related distance is smaller than innerR
            idxout = (tmp < innerR)

        # Put the x, y-coordiate to be NaN if it is inside/ outside the pupil that is 
        # after the off-axis correction.
        lutx[idxout] = np.nan
        luty[idxout] = np.nan

        # Get the x, y-coordinate in this ring area by the linear approximation
        lutx[idxbound] = (lutx[idxbound]-cenX)/lutr[idxbound]*R + cenX
        luty[idxbound] = (luty[idxbound]-cenY)/lutr[idxbound]*R + cenY

        return lutx, luty

    def __rotateMaskParam(self, ca, cb, fieldX, fieldY):
        """
        
        Rotate the mask-related parameters of center.
        
        Arguments:
            ca {[float]} -- Mask-related parameter of center.
            cb {float} -- Mask-related parameter of center.
            fieldX {[float]} -- x-coordinate of donut on the focal plane in degree.
            fieldY {[float]} -- y-coordinate of donut on the focal plane in degree.
        
        Returns:
            [float] -- Projected x, y elements
        """

        # Calculate the sin(theta) and cos(theta) for the rotation
        fldr = np.sqrt(fieldX**2 + fieldY**2)
        if (fldr == 0):
            c = 0
            s = 0
        else:
            # Calculate cos(theta)
            c = fieldX/fldr

            # Calculate sin(theta)
            s = fieldY/fldr

        # Projected x and y coordinate after the rotation
        cax = c*ca
        cay = s*ca

        cbx = c*cb
        cby = s*cb

        return cax, cay, cbx, cby

    def getOffAxisCorr(self, instDir, order):
        """
        
        Map the coefficients of off-axis correction for x, y-projection of intra- and 
        extra-image. This is for the mapping of coordinate from the telescope apearature 
        to defocal image plane.
        
        Arguments:
            instDir {[string]} -- Path to specific instrument directory.
            order {[int]} -- Up to order-th of off-axis correction.
        """

        # List of configuration
        configList = ["cxin", "cyin", "cxex", "cyex"]

        # Get all files in the directory
        fileList = [f for f in os.listdir(instDir) if os.path.isfile(os.path.join(instDir, f))]

        # Read files
        temp = []

        for config in configList:

            # Construct the configuration file name
            for fileName in fileList:
                m = re.match(r"\S*%s\S*.txt" % config, fileName)
                if (m is not None):
                    matchFileName = m.group()
                    break
            filePath = os.path.join(instDir, matchFileName)

            # Read the file
            corr_coeff, offset = self.__getOffAxisCorr_single(filePath)
            temp.append(corr_coeff)

        # Give the values
        self.offAxis_coeff = np.array(temp)
        self.offAxisOffset = offset

    def __getOffAxisCorr_single(self, confFile):
        """
        
        Get the image-related pamameters for the off-axis distortion by the linear 
        approximation with a series of fitted parameters with LSST ZEMAX model.
        
        Arguments:
            confFile {[string]} -- Path of configuration file.
        
        Returns:
            [float] -- Coefficients for the off-axis distortion based on the linear 
                       response.
            [float] -- Defocal distance in m.
        """

        # Calculate the distance from donut to origin (aperature)
        fldr = np.sqrt(self.fieldX**2 + self.fieldY**2)

        # Read the configuration file
        cdata = np.loadtxt(confFile)
                        
        # Record the offset (defocal distance)
        offset = cdata[0, 0]

        # Take the reference parameters
        c = cdata[:, 1:]

        # Get the ruler, which is the distance to center
        # ruler is between 1.51 and 1.84 degree here   
        ruler = np.sqrt(c[:, 0]**2 + c[:, 1]**2)

        # Get the fitted parameters for off-axis correction by linear approximation
        corr_coeff = self.__linearApprox(fldr, ruler, c[:, 2:])
    
        return corr_coeff, offset

    def __interpMaskParam(self, fieldX, fieldY, maskParam):
        """
        
        Get the mask-related pamameters for the off-axis distortion and vignetting correction 
        by the linear approximation with a series of fitted parameters with LSST ZEMAX model.
        
        Arguments:
            fieldX {[float]} -- x-coordinate of donut on the focal plane in degree.
            fieldY {[float]} -- y-coordinate of donut on the focal plane in degree.
            maskParam {[string]} -- Fitted coefficient file for the off-axis distortion and 
                                    vignetting correction 
        
        Returns:
            [float] -- Coefficients for the off-axis distortion and vignetting correction based 
                       on the linear response.
        """

        # Calculate the distance from donut to origin (aperature)
        fldr = np.sqrt(fieldX**2 + fieldY**2)
        
        # Load the mask parameter
        c = np.loadtxt(maskParam)

        # Get the ruler, which is the distance to center
        # ruler is between 1.51 and 1.84 degree here    
        ruler = np.sqrt(2)*c[:, 0]

        # Get the fitted parameters for off-axis correction by linear approximation
        param = self.__linearApprox(fldr, ruler, c[:, 1:])

        # Define related parameters
        ca = param[0]
        ra = param[1]
        cb = param[2]
        rb = param[3]
    
        return ca, ra, cb, rb

    def __linearApprox(self, fldr, ruler, parameters):
        """
        
        Get the fitted parameters for off-axis correction by linear approximation
        
        Arguments:
            fldr {[float]} -- Distance from donut to origin (aperature).
            ruler {[float]} -- A series of distance with available parameters for the fitting.
            parameters {[float]} -- Referenced parameters for the fitting.
        
        Returns:
            [float] -- Fitted parameters based on the linear approximation.
        """

        # Sort the ruler and parameters based on the magnitude of ruler
        sortIndex = np.argsort(ruler)
        ruler = ruler[sortIndex]
        parameters = parameters[sortIndex, :]

        # Compare the distance to center (aperature) between donut and standard
        compDis = (ruler >= fldr)

        # fldr is too big and out of range
        if (fldr > ruler.max()):  
            # Take the coefficients in the highest boundary
            p2 = c.shape[0]-1
            p1 = 0            
            w1 = 0
            w2 = 1

        # fldr is too small to be in the range
        elif (fldr < ruler.min()):  
            # Take the coefficients in the lowest boundary
            p2 = 0
            p1 = 0
            w1 = 1
            w2 = 0

        # fldr is in the range
        else:
            # Find the boundary of fldr in the known data
            p2 = compDis.argmax()
            p1 = p2 - 1

            # Calculate the weighting ratio
            w1 = (ruler[p2]-fldr)/(ruler[p2]-ruler[p1])
            w2 = 1-w1

        # Get the fitted parameters for off-axis correction by linear approximation
        param = w1*parameters[p1, :] + w2*parameters[p2, :]

        return param

    def makeMaskList(self, inst, model):
        """
        
        Calculate the mask list based on the obscuration and optical model.
        
        Arguments:
            inst {[Instrument]} -- Instrument to use.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
        """

        # Masklist = [center_x, center_y, radius_of_boundary, 1/ 0 for outer/ inner boundary]
        obscuration = inst.parameter["obscuration"]
        if (model in ("paraxial", "onAxis")):

            if (obscuration == 0):
                masklist = np.array([0, 0, 1, 1])
            else:
                masklist = np.array([[0, 0, 1, 1],
                                          [0, 0, obscuration, 0]])
        else:
            # Get the mask-related parameters
            maskCa, maskRa, maskCb, maskRb = self.__interpMaskParam(self.fieldX, 
                                                        self.fieldY, inst.maskParam)

            # Rotate the mask-related parameters of center
            cax, cay, cbx, cby = self.__rotateMaskParam(maskCa, maskCb, self.fieldX, self.fieldY)
            masklist = np.array([[0, 0, 1, 1], [0, 0, obscuration, 0], 
                                 [cax, cay, maskRa, 1], [cbx, cby, maskRb, 0]])

        return masklist

    def __showProjection(self, lutxp, lutyp, sensorFactor, projSamples, raytrace=False):
        """
        
        Calculate the x, y-projection of image on pupil. This can be used to calculate 
        the center of projection in compensate().
        
        Arguments:
            lutxp {[float]} -- x-coordinate on pupil plane. The value of element will be 
                               NaN if that point is not inside the pupil.
            lutyp {[float]} -- y-coordinate on pupil plane. The value of element will be 
                               NaN if that point is not inside the pupil.
            sensorFactor {[float]} -- ? (Need to check the meaning of this.)
            projSamples {[int]} -- Dimension of projected image. This value considers the
                                   magnification ratio of donut image.
            raytrace {[bool]} -- Consider the ray trace or not. If the value is true, the 
                                 times of photon hit will aggregate. (default: {False})
        
        Returns:
            [float] -- Projection of image. It will be a binary image if raytrace=False.
        """

        # Dimension of pupil image
        n1, n2 = lutxp.shape

        # Construct the binary matrix on pupil. It is noted that if the raytrace is true, 
        # the value of element is allowed to be greater than 1.
        show_lutxyp = np.zeros([n1, n2])

        # Get the index in pupil. If a point's value is NaN, this point is outside the pupil.        
        idx = (~np.isnan(lutxp)).nonzero()
        for ii, jj in zip(idx[0], idx[1]):
            # Calculate the projected x, y-coordinate in pixel
            # x=0.5 is center of pixel#1
            xR = int(np.round((lutxp[ii, jj]+sensorFactor)*projSamples/sensorFactor/2 + 0.5))
            yR = int(np.round((lutyp[ii, jj]+sensorFactor)*projSamples/sensorFactor/2 + 0.5))
    
            # Check the projected coordinate is in the range of image or not.
            # If the check passes, the times will be recorded.
            if (xR>0 and xR<n2 and yR>0 and yR<n1):
                # Aggregate the times
                if raytrace:
                    show_lutxyp[yR-1, xR-1] += 1
                # No aggragation of times
                else:
                    if (show_lutxyp[yR-1, xR-1] < 1):
                        show_lutxyp[yR-1, xR-1] = 1

        return show_lutxyp

    def makeMask(self, inst, model, boundaryT, maskScalingFactorLocal):
        """
        
        Get the binary mask which considers the obscuration and off-axis correction.
        There will be two mask parameters to be calculated:
        pMask: padded mask for use at the offset planes
        cMask: non-padded mask corresponding to aperture
        
        Arguments:
            inst {[Instrument]} -- Instrument to use.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
            boundaryT {[int]} -- Extended boundary in pixel. It defines how far the 
                                 computation mask extends beyond the pupil mask. And, 
                                 in fft, it is also the width of Neuman boundary where 
                                 the derivative of the wavefront is set to zero.
            maskScalingFactorLocal {[float]} -- Mask scaling factor (for fast beam) for
                                                local correction.
        """

        sensorSamples = inst.parameter["sensorSamples"]
        self.pMask = np.ones(sensorSamples, dtype=int)
        self.cMask = self.pMask.copy()

        apertureDiameter = inst.parameter["apertureDiameter"]
        focalLength = inst.parameter["focalLength"]
        offset = inst.parameter["offset"]
        rMask = apertureDiameter/(2*focalLength/offset)*maskScalingFactorLocal

        # Get the mask list
        masklist = self.makeMaskList(inst, model)

        for ii in range(masklist.shape[0]):

            # Distance to center on pupil
            r = np.sqrt((inst.xSensor - masklist[ii, 0])**2 +
                        (inst.ySensor - masklist[ii, 1])**2)
            
            # Find the indices that correspond to the mask element, set them to
            # the pass/ block boolean

            # Get the index inside the aperature
            idx = (r <= masklist[ii, 2])
                        
            # Get the higher and lower boundary beyond the pupil mask by extension.
            # The extension level is dicided by boundaryT.
            # In fft, this is also the Neuman boundary where the derivative of the 
            # wavefront is set to zero.
            pixelSize = inst.parameter["pixelSize"]
            if (masklist[ii, 3] >= 1):
                aidx = np.nonzero( r <= masklist[ii, 2]*(1+boundaryT*pixelSize/rMask) )
            else:
                aidx = np.nonzero( r <= masklist[ii, 2]*(1-boundaryT*pixelSize/rMask) )

            # Initialize both mask elements to the opposite of the pass/ block boolean
            pMaskii = (1 - masklist[ii, 3]) * \
                        np.ones([sensorSamples, sensorSamples], dtype=int)
            cMaskii = pMaskii.copy()

            pMaskii[idx] = masklist[ii, 3]
            cMaskii[aidx] = masklist[ii, 3]

            # Multiplicatively add the current mask elements to the model masks.
            # This is try to find the common mask region.

            # padded mask for use at the offset planes
            self.pMask = self.pMask*pMaskii
            # non-padded mask corresponding to aperture
            self.cMask = self.cMask*cMaskii


class tempAlgo(object):
    """
    
    Temporary algorithm class used for the testing.
    """

    def __init__(self):
        self.parameter = None

class CompensationImageDecoratorTest(unittest.TestCase):

    """
    Test functions in CompensationImageDecorator.
    """
    def setUp(self):

        # Get the path of module
        modulePath = getModulePath()
        
        # Define the instrument folder
        instruFolder = os.path.join(modulePath, "algoData", "cwfs", "instruData")

        # Define the instrument name
        instruName = "lsst"
        sensorSamples = 120

        self.inst = Instrument(instruFolder)
        self.inst.config(instruName, sensorSamples)

        # Define the image folder and image names
        # Image data -- Don't know the final image format.
        # It is noted that image.readFile inuts is based on the txt file
        imageFolderPath = os.path.join(modulePath, "test", "testImages", "LSST_NE_SN25")
        intra_image_name = "z11_0.25_intra.txt"
        extra_image_name = "z11_0.25_extra.txt"
        self.imgFilePathIntra = os.path.join(imageFolderPath, intra_image_name)
        self.imgFilePathExtra = os.path.join(imageFolderPath, extra_image_name)

        # Define fieldXY: [1.185, 1.185] or [0, 0]
        # This is the position of donut on the focal plane in degree
        self.fieldXY = [1.185, 1.185]

        # Define the optical model: "paraxial", "onAxis", "offAxis"
        self.opticalModel = "offAxis"

        # Get the true Zk
        zcAnsFilePath = os.path.join(modulePath, "test", "testImages", "validation", "LSST_NE_SN25_z11_0.25_exp.txt")
        self.zcCol = np.loadtxt(zcAnsFilePath)

    def testFunc(self):

        # Declare the CompensationImageDecorator
        wfsImg = CompensationImageDecorator()

        # Test to set the image
        wfsImg.setImg(self.fieldXY, imageFile=self.imgFilePathIntra, atype="intra")
        self.assertEqual(wfsImg.image.shape, (120, 120))
        self.assertEqual(wfsImg.fieldX, self.fieldXY[0])
        self.assertEqual(wfsImg.fieldY, self.fieldXY[1])

        # Test to update the image0
        wfsImg.updateImage0()
        self.assertEqual(np.sum(np.abs(wfsImg.image0-wfsImg.image)), 0)

        # Test to get the off axis correction
        offAxisCorrOrder = 10
        instDir = os.path.join(self.inst.instDir, self.inst.instName)
        wfsImg.getOffAxisCorr(instDir, offAxisCorrOrder)
        self.assertEqual(wfsImg.offAxisOffset, 0.001)
        self.assertEqual(wfsImg.offAxis_coeff.shape, (4, 66))
        self.assertAlmostEqual(wfsImg.offAxis_coeff[0, 0], -2.6362089*1e-3)

        # Test to make the mask list
        model = "paraxial"
        masklist = wfsImg.makeMaskList(self.inst, model)
        masklistAns = np.array([[0, 0, 1, 1], [0, 0, 0.61, 0]])
        self.assertEqual(np.sum(np.abs(masklist-masklistAns)), 0)

        model = "offAxis"
        masklist = wfsImg.makeMaskList(self.inst, model)
        masklistAns = np.array([[0, 0, 1, 1], [0, 0, 0.61, 0], 
                                [-0.21240585, -0.21240585, 1.2300922, 1], 
                                [-0.08784336, -0.08784336, 0.55802573, 0]])
        self.assertAlmostEqual(np.sum(np.abs(masklist-masklistAns)), 0)

        # Test the fuction to make the mask

        # The unit of boundary_thickness (boundaryT) is pixel
        boundaryT = 8
        maskScalingFactorLocal = 1
        model = "offAxis"
        wfsImg.makeMask(self.inst, model, boundaryT, maskScalingFactorLocal)
        self.assertEqual(wfsImg.pMask.shape, wfsImg.image.shape)
        self.assertEqual(wfsImg.cMask.shape, wfsImg.image.shape)
        self.assertEqual(np.sum(np.abs(wfsImg.cMask - wfsImg.pMask)), 3001)

        # Test the function of image co-center
        wfsImg.imageCoCenter(self.inst)
        xc, yc = wfsImg.getCenterAndR_ef()[0:2]
        self.assertAlmostEqual(xc, 63.223939929328623)
        self.assertAlmostEqual(yc, 63.226810954063602)

    def testFuncCompensation(self):

        # Generate a fake algorithm class
        algo = tempAlgo()
        algo.parameter = {"numTerms": 22, "offAxisPolyOrder": 10, "zobsR": 0.61}

        # Test the function of image compensation
        boundaryT = 8
        offAxisCorrOrder = 10
        zcCol = np.zeros(22)
        zcCol[3:] = self.zcCol*1e-9
        instDir = os.path.join(self.inst.instDir, self.inst.instName)

        wfsImgIntra = CompensationImageDecorator()
        wfsImgExtra = CompensationImageDecorator()
        wfsImgIntra.setImg(self.fieldXY, imageFile=self.imgFilePathIntra, atype="intra")
        wfsImgExtra.setImg(self.fieldXY, imageFile=self.imgFilePathExtra, atype="extra")

        for wfsImg in [wfsImgIntra, wfsImgExtra]:
            wfsImg.makeMask(self.inst, self.opticalModel, boundaryT, 1)
            wfsImg.getOffAxisCorr(instDir, offAxisCorrOrder)
            wfsImg.imageCoCenter(self.inst)
            wfsImg.compensate(self.inst, algo, zcCol, self.opticalModel)

        # Get the common region
        binaryImgIntra = wfsImgIntra.getCenterAndR_ef()[3]
        binaryImgExtra = wfsImgExtra.getCenterAndR_ef()[3]
        binaryImg = binaryImgIntra+binaryImgExtra
        binaryImg[binaryImg<2] = 0
        binaryImg = binaryImg/2

        # Calculate the difference
        res = np.sum(np.abs(wfsImgExtra.image-wfsImgIntra.image)*binaryImg)

        self.assertLess(res, 250)

if __name__ == "__main__":

    # Do the unit test
    unittest.main()