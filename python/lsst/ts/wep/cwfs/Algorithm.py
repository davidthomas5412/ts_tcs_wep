#!/usr/bin/env python
##
##
# @authors: Bo Xin & Chuck Claver
# @       Large Synoptic Survey Telescope
##
# The FFT algorithm in solvePoissonEq() is partly based on some earlier code
# written by William P. Kuhn
##
# Refactored by Te-Wei Tsai at June, 2017
##

import os, sys, unittest
import numpy as np

import matplotlib
# Must be before importing matplotlib.pyplot or pylab!
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scipy.ndimage import generate_binary_structure, iterate_structure
from scipy.ndimage.filters import laplace
from scipy.ndimage.morphology import binary_dilation, binary_erosion

from lsst.ts.wep.cwfs.Tool import padArray, extractArray, ZernikeAnnularEval, ZernikeMaskedFit, ZernikeAnnularGrad
from lsst.ts.wep.cwfs.Instrument import Instrument
from lsst.ts.wep.cwfs.CompensationImageDecorator import CompensationImageDecorator
from lsst.ts.wep.Utility import getModulePath

class Algorithm(object):

    def __init__(self, algoFolder):
        """

        Algorithm used to solve the transport of intensity equation to get
        normal/ annular Zernike polynomials.

        Arguments:
            algoFolderPath {[str]} -- Path to algorithm folder.
        """

        # Record the file name/ path
        self.algoDir = algoFolder

        # Patameters of algorithm
        self.filename = None
        self.parameter = None
        self.caustic = False
        self.converge = None
        self.debugLevel = 0
        self.currentItr = 0
        self.zer4UpNm = None
        self.wcomp = None
        self.West = None
        self.zcomp = None
        self.zc = None
        self.pMask = None
        self.cMask = None
        self.pMaskPad = None
        self.cMaskPad = None
        self.algoName = None

    def reset(self):
        """
        
        Reset the calculation for the new input images with the same algorithm settings.
        """

        self.caustic = False
        self.converge = np.zeros(self.converge.shape)
        self.currentItr = 0
        self.zer4UpNm = np.zeros(self.zer4UpNm.shape)
        self.wcomp = np.zeros(self.wcomp.shape)
        self.West = np.zeros(self.West.shape)
        self.zcomp = np.zeros(self.zcomp.shape)
        self.zc = np.zeros(self.zc.shape)
        self.pMask = None
        self.cMask = None
        self.pMaskPad = None
        self.cMaskPad = None

    def config(self, algoName, inst, debugLevel=0):
        """
        
        Configure the algorithm to solve TIE.
        
        Arguments:
            algoName {[str]} -- Algorithm configuration file to solve the Poisson's equation
                                in the transport of intensity equation (TIE). It can be "fft"
                                or "exp" here.
            inst {[Instrument]} -- Instrument to use.
        
        Keyword Arguments:
            debugLevel {int} -- Show the information under the running. If the value is higher,
                                the information shows more. It can be 0, 1, 2, or 3. (default: {0})
        """

        # Name of algorithm
        self.algoName = algoName

        # Record the file name/ path
        self.filename = os.path.join(self.algoDir, "%s.algo" % algoName)

        # Get the parameters of algorithm
        self.parameter = self.__readFile(self.algoDir, self.filename, inst)

        # Check the image has the problem or not
        self.caustic = False

        # Record the Zk coefficients in each outer-loop iteration
        # The actual total outer-loop iteration time is Num_of_outer_itr + 1.
        numTerms = self.parameter["numTerms"]
        outerItr = self.parameter["outerItr"]
        self.converge = np.zeros([numTerms, outerItr + 1])

        # Assign the debug level
        self.debugLevel = debugLevel

        # Current number of outer-loop iteration
        self.currentItr = 0

        # Record the coefficients of normal/ annular Zernike polynomials after z4
        # in unit of nm
        self.zer4UpNm = np.zeros(numTerms-3)

        # Dimension of sensor samples in instrument
        sensorSamples = inst.parameter["sensorSamples"]

        # Wavefront-related parameters
        # wcomp: Converged wavefront.
        # West: Calculated wavefront in previous outer-loop iteration.
        self.wcomp = np.zeros([sensorSamples, sensorSamples])
        self.West = self.wcomp.copy()

        # Used in model basis ("zer").
        # zcomp: Converged Zk coefficients.
        # zc: Calculated Zk coefficients in previous outer-loop iteration.
        self.zcomp = np.zeros(numTerms)
        self.zc = self.zcomp.copy()

        # Mask related variables
        # padded mask for use at the offset planes
        self.pMask = None
        # non-padded mask corresponding to aperture
        self.cMask = None

        # Change the dimension of mask for fft to use
        self.pMaskPad = None
        self.cMaskPad = None

    def __readFile(self, algoFolderPath, filename, inst):
        """
        
        Read the algorithm file and calculate the parameters in algorithm.
        
        Arguments:
            algoFolderPath {[str]} -- Path to algorithm folder.
            filename {[str]} -- File name of algorithm configuration.
            inst {[Instrument]} -- Instrument to use.
        
        Returns:
            [dict] -- Parameters in algorithm.
        """

        # Parameters specialzied for "fft" compared with "exp"
        # Do not find the use of ZTerms in code actually
        ZTerms = None
        padDim = None
        innerItr = None
        sumclipSequence = None

        # Open the file to read parameters used in the algorithm
        fid = open(filename)
        iscomment = False
        for line in fid:
            line = line.strip()

            # Use to skip the comment information in the file
            if (line.startswith("###")):
                iscomment = ~iscomment

            if (not(line.startswith("#")) and (not iscomment) and len(line) > 0):

                if (line.startswith("PoissonSolver")):
                    PoissonSolver = line.split()[1]

                elif (line.startswith("Num_of_Zernikes")):
                    numTerms = int(line.split()[1])

                elif (line.startswith("ZTerms")):
                    ZTerms = np.hstack(([1, 2, 3], [int(x) for x in line.split()[1:]]))

                elif (line.startswith("Num_of_outer_itr")):
                    outerItr = int(line.split()[1])

                elif (line.startswith("Num_of_inner_itr")):
                    innerItr = int(line.split()[1])

                elif (line.startswith("Zernikes")):
                    zobsR = float(line.split()[1])

                elif (line.startswith("FFT_dimension")):
                    padDim = int(line.split()[2])

                elif (line.startswith("Feedback_gain")):
                    feedbackGain = float(line.split()[1])

                elif (line.startswith("Compensator_oversample")):
                    compOversample = float(line.split()[1])

                elif (line.startswith("Compensator_mode")):
                    compMode = line.split()[1]

                elif (line.startswith("OffAxis_poly_order")):
                    offAxisPolyOrder = int(line.split()[1])

                elif (line.startswith("Boundary_thickness")):
                    boundaryT = int(line.split()[2])

                elif (line.startswith("Compensation_sequence")):
                    compSequence = np.loadtxt(os.path.join(algoFolderPath, line.split()[1]))

                elif (line.startswith("Sumclip_sequence")):
                    sumclipSequence = np.loadtxt(os.path.join(algoFolderPath, line.split()[1]))

        # Close the file
        fid.close()

        # Give the values of ZTerms. Need to check why this is needed. Not find this variable is used.
        if (ZTerms is None):
            ZTerms = np.arange(numTerms) + 1

        # Get the obscuration ratio in baseline
        if (zobsR):
            if (zobsR == 1):
                zobsR = inst.parameter["obscuration"]

        # If outerItr is large, and compSequence is too small,
        # the rest in compSequence will be filled.
        if (compSequence.shape[0] < outerItr):

            # For "zer" mode
            if (len(compSequence.shape) == 1):
                # Resize compSequence to be outerItr and
                # set all etra values to compSequence[-1].
                compSequence = np.append(compSequence,
                                         compSequence[-1]*np.ones(outerItr-compSequence.shape[0]))

        # Dimension of sensor samples in instrument
        sensorSamples = inst.parameter["sensorSamples"]

        # Check the parameters used in the fft
        if (PoissonSolver == "fft"):

            # If outerItr is large, and sumclipSequence is too small,
            # the rest in sumclipSequence will be filled.
            if (sumclipSequence.shape[0] < outerItr+1):

                # For "zer" mode
                if (len(sumclipSequence.shape) == 1):
                    # Resize sumclipSequence to be outerItr and
                    # set all etra values to sumclipSequence[-1].
                    sumclipSequence = np.append(sumclipSequence,
                                          sumclipSequence[-1]*np.ones(outerItr+1-sumclipSequence.shape[0]))

            # Make sure the dimension is the order of multiple of 2
            if (padDim == 999):
                # Enforce to be "int" type because the output of np.ceil is "float"
                padDim = int(2**np.ceil(np.log2(sensorSamples)))
            else:
                # Enforce to be "int" type because the output of np.ceil is "float"
                padDim = int(2**np.ceil(np.log2(padDim)))

        # Mask scaling factor (for fast beam)
        # m = R'*f/(l*R), R': radius of the no-aberration image
        maskScalingFactor = inst.parameter["focalLength"]/inst.parameter["marginalFL"]

        # Collect all parameters of algorithm into a single dictionary attribute
        parameter = {"PoissonSolver": PoissonSolver,
                     "numTerms": numTerms,
                     "ZTerms": ZTerms,
                     "outerItr": outerItr,
                     "innerItr": innerItr,
                     "zobsR": zobsR,
                     "padDim": padDim,
                     "feedbackGain": feedbackGain,
                     "compOversample": compOversample,
                     "compMode": compMode,
                     "offAxisPolyOrder": offAxisPolyOrder,
                     "boundaryT": boundaryT,
                     "compSequence": compSequence,
                     "sumclipSequence": sumclipSequence,
                     "maskScalingFactor": maskScalingFactor}

        return parameter

    def itr0(self, inst, I1, I2, model):
        """

        Calculate the wavefront and coefficients of normal/ annular Zernike polynomials in the
        first iteration time.

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
        """

        # Reset the iteration time of outer loop and decide to reset the defocal
        # images or not
        self.__reset(I1, I2)

        # Solve the transport of intensity equation (TIE)
        self.__singleItr(inst, I1, I2, model)

    def runIt(self, inst, I1, I2, model, tol=1e-3):
        """

        Calculate the wavefront error by solving the transport of intensity equation (TIE).
        The inner (for fft algorithm) and outer loops are used. The inner loop is to solve
        the Poisson's equation. The outer loop is to compensate the intra- and extra-focal
        images to mitigate the calculation of wavefront
        (e.g. S = -1/(delta Z) * (I1 - I2)/ (I1 + I2)).

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
            tol {[float]} -- Tolerance of difference of coefficients of Zk polynomials compared with
                             the previours iteration.
        """

        # To have the iteration time initiated from global variable is to distinguish the manually
        # and automatically iteration processes.
        itr = self.currentItr
        while (itr <= self.parameter["outerItr"]):
            stopItr = self.__singleItr(inst, I1, I2, model, tol)

            # Stop the iteration of outer loop if converged
            if (stopItr):
                break

            itr += 1

    def nextItr(self, inst, I1, I2, model, nItr=1):
        """

        Run the outer loop iteration with the specific time defined in nItr.

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".

        Keyword Arguments:
            nItr {int} -- Outer loop iteration time (default: {1}).
        """

        #  Do the iteration
        ii = 0
        while (ii < nItr):
            self.__singleItr(inst, I1, I2, model)
            ii += 1

    def setDebugLevel(self, debugLevel):
        """

        Set the debug level.

        Arguments:
            debugLevel {[int]} -- Show the information under the running. If the value is higher,
                                  the information shows more. It can be 0, 1, 2, or 3.
        """

        # Set the debug level
        self.debugLevel = debugLevel

    def __singleItr(self, inst, I1, I2, model, tol=1e-3):
        """

        Run the outer-loop with single iteration to solve the transport of intensity equation (TIE).
        This is to compensate the approximation of wavefront S = -1/(delta Z) * (I1 - I2)/ (I1 + I2)).

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
            model {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
            tol {[float]} -- Tolerance of difference of coefficients of Zk polynomials compared with
                             the previours iteration.
        """

        # Use the zonal mode ("zer")
        compMode = self.parameter["compMode"]

        # Define the gain of feedbackGain
        feedbackGain = self.parameter["feedbackGain"]

        # Set the pre-condition
        if (self.currentItr == 0):

            # Check this is the first time of running iteration or not
            if (I1.image0 is None or I2.image0 is None):

                # Check the image dimension
                if (I1.image.shape != I2.image.shape):
                    print("Error: The intra and extra image stamps need to be of same size.")
                    sys.exit()

                # Calculate the pupil mask (binary matrix) and related parameters
                I1.makeMask(inst, model, self.parameter["boundaryT"], 1)
                I2.makeMask(inst, model, self.parameter["boundaryT"], 1)
                self.__makeMasterMask(I1, I2, self.parameter["PoissonSolver"])

                # Load the offAxis correction coefficients
                if (model == "offAxis"):
                    instDir = os.path.join(inst.instDir, inst.instName)
                    I1.getOffAxisCorr(instDir, self.parameter["offAxisPolyOrder"])
                    I2.getOffAxisCorr(instDir, self.parameter["offAxisPolyOrder"])

                # Cocenter the images to the center referenced to fieldX and fieldY. Need to check the
                # availability of this.
                I1.imageCoCenter(inst, debugLevel=self.debugLevel)
                I2.imageCoCenter(inst, debugLevel=self.debugLevel)

                # Update the self-initial image
                I1.updateImage0()
                I2.updateImage0()

            # Initialize the variables used in the iteration.
            self.zcomp = np.zeros(self.parameter["numTerms"])
            self.zc = self.zcomp.copy()

            sensorSamples = inst.parameter["sensorSamples"]
            self.wcomp = np.zeros([sensorSamples, sensorSamples])
            self.West = self.wcomp.copy()

            self.caustic = False

        # Rename this index (currentItr) for the simplification
        jj = self.currentItr

        # Solve the transport of intensity equation (TIE)
        if (not self.caustic):

            # Reset the images before the compensation
            I1.updateImage(I1.image0.copy())
            I2.updateImage(I2.image0.copy())

            if (compMode == "zer"):

                # Zk coefficient from the previous iteration
                ztmp = self.zc

                # Do the feedback of Zk from the lower terms first based on the
                # sequence defined in compSequence
                if (jj != 0):
                    compSequence = self.parameter["compSequence"]
                    ztmp[int(compSequence[jj - 1]):] = 0

                # Add partial feedback of residual estimated wavefront in Zk
                self.zcomp = self.zcomp + ztmp*feedbackGain

                # Remove the image distortion if the optical model is not "paraxial"
                # Only the optical model of "onAxis" or "offAxis" is considered here
                I1.compensate(inst, self, self.zcomp, model)
                I2.compensate(inst, self, self.zcomp, model)

            # Check the image condition. If there is the problem, done with this __singleItr().
            if (I1.caustic == True or I2.caustic == True):
                self.converge[:, jj] = self.converge[:, jj - 1]
                self.caustic = True
                return

            # Correct the defocal images if I1 and I2 are belong to different
            # sources, which is determined by the (fieldX, field Y)
            I1, I2 = self.__applyI1I2pMask(I1, I2)

            # Solve the Poisson's equation
            self.zc, self.West = self.__solvePoissonEq(inst, I1, I2, jj)

            # Record/ calculate the Zk coefficient and wavefront
            if (compMode == "zer"):
                self.converge[:, jj] = self.zcomp + self.zc
                self.wcomp = self.West + ZernikeAnnularEval(
                                                    np.concatenate(([0, 0, 0], self.zcomp[3:])),
                                                    inst.xoSensor, inst.yoSensor,
                                                    self.parameter["zobsR"])

        else:
            # Once we run into caustic, stop here, results may be close to real aberration.
            # Continuation may lead to disatrous results.
            self.converge[:, jj] = self.converge[:, jj - 1]

        # Record the coefficients of normal/ annular Zernike polynomials after z4
        # in unit of nm
        self.zer4UpNm = self.converge[3:, jj]*1e9

        # Status of iteration
        stopItr = False

        # Calculate the difference
        if (jj>0):
            diffZk = np.sum(np.abs(self.converge[:, jj]-self.converge[:, jj-1]))*1e9

            # Check the Status of iteration
            if (diffZk < tol):
                stopItr = True

        # Update the current iteration time
        self.currentItr += 1

        # Show the Zk coefficients in interger in each iteration
        if (self.debugLevel >= 2):
            tmp = self.zer4UpNm
            print("itr = %d, z4-z%d" % (jj, self.parameter["numTerms"]))
            print(np.rint(tmp))

        return stopItr

    def __solvePoissonEq(self, inst, I1, I2, iOutItr=0):
        """

        Solve the Poisson's equation by Fourier transform (differential) or serial expansion
        (integration).

        There is no convergence for fft actually. Need to add the difference comparison and
        Xa method. Need to discuss further for this.

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.

        Keyword Arguments:
            iOutItr {[int]} -- ith number of outer loop iteration which is important
                               in "fft" algorithm (default: {0}).

        Returns:
            [float] -- Coefficients of normal/ annular Zernike polynomials.
            [float] -- Estimated wavefront.
        """

        # Calculate the aperature pixel size
        apertureDiameter = inst.parameter["apertureDiameter"]
        sensorFactor = inst.parameter["sensorFactor"]
        sensorSamples = inst.parameter["sensorSamples"]
        aperturePixelSize = apertureDiameter*sensorFactor/sensorSamples

        # Calculate the differential Omega
        dOmega = aperturePixelSize**2

        # Solve the Poisson's equation based on the type of algorithm
        numTerms = self.parameter["numTerms"]
        zobsR = self.parameter["zobsR"]
        PoissonSolver = self.parameter["PoissonSolver"]
        if (PoissonSolver == "fft"):

            # Use the differential method by fft to solve the Poisson's equation

            # Parameter to determine the threshold of calculating I0.
            sumclipSequence = self.parameter["sumclipSequence"]
            cliplevel = sumclipSequence[iOutItr]

            # Generate the v, u-coordinates on pupil plane
            padDim = self.parameter["padDim"]
            v, u = np.mgrid[
                -0.5/aperturePixelSize: 0.5/aperturePixelSize: 1./padDim/aperturePixelSize,
                -0.5/aperturePixelSize: 0.5/aperturePixelSize: 1./padDim/aperturePixelSize]

            # Show the threshold and pupil coordinate information
            if (self.debugLevel >= 3):
                print("iOuter=%d, cliplevel=%4.2f" % (iOutItr, cliplevel))
                print(v.shape)

            # Calculate the const of fft: FT{Delta W} = -4*pi^2*(u^2+v^2) * FT{W}
            u2v2 = -4 * (np.pi**2) * (u*u + v*v)

            # Set origin to Inf to result in 0 at origin after filtering
            ctrIdx = int(np.floor(padDim/2.0))
            u2v2[ctrIdx, ctrIdx] = np.inf

            # Calculate the wavefront signal
            Sini = self.__createSignal(inst, I1, I2, cliplevel)

            # Find the just-outside and just-inside indices of a ring in pixels
            # This is for the use in setting dWdn = 0
            boundaryT = self.parameter["boundaryT"]

            struct = generate_binary_structure(2, 1)
            struct = iterate_structure(struct, boundaryT)

            ApringOut = np.logical_xor(binary_dilation(self.pMask, structure=struct),
                                       self.pMask).astype(int)
            ApringIn = np.logical_xor(binary_erosion(self.pMask, structure=struct),
                                      self.pMask).astype(int)

            bordery, borderx = np.nonzero(ApringOut)

            # Put the signal in boundary (since there's no existing Sestimate, S just equals self.S
            # as the initial condition of SCF
            S = Sini.copy()
            for jj in range(int(self.parameter["innerItr"])):

                # Calculate FT{S}
                SFFT = np.fft.fftshift(np.fft.fft2(np.fft.fftshift(S)))

                # Calculate W by W=IFT{ FT{S}/(-4*pi^2*(u^2+v^2)) }
                W = np.fft.fftshift(np.fft.irfft2(np.fft.fftshift(SFFT/u2v2), s=S.shape))

                # Estimate the wavefront (includes zeroing offset & masking to the aperture size)

                # Take the estimated wavefront
                West = extractArray(W, sensorSamples)

                # Calculate the offset
                offset = West[self.pMask==1].mean()
                West = West - offset
                West[self.pMask==0] = 0

                # Set dWestimate/dn = 0 around boundary
                WestdWdn0 = West.copy()

                # Do a 3x3 average around each border pixel, including only those pixels
                # inside the aperture
                for ii in range(len(borderx)):
                    reg = West[borderx[ii] - boundaryT:
                               borderx[ii] + boundaryT + 1,
                               bordery[ii] - boundaryT:
                               bordery[ii] + boundaryT + 1]

                    intersectIdx = ApringIn[borderx[ii] - boundaryT:
                                            borderx[ii] + boundaryT + 1,
                                            bordery[ii] - boundaryT:
                                            bordery[ii] + boundaryT + 1]

                    WestdWdn0[borderx[ii], bordery[ii]] = reg[np.nonzero(intersectIdx)].mean()

                # Take Laplacian to find sensor signal estimate (Delta W = S)
                del2W = laplace(WestdWdn0)/dOmega

                # Extend the dimension of signal to the order of 2 for "fft" to use
                Sest = padArray(del2W, padDim)

                # Put signal back inside boundary, leaving the rest of Sestimate
                Sest[self.pMaskPad==1] = Sini[self.pMaskPad==1]

                # Need to recheck this condition
                S = Sest

            # Define the estimated wavefront
            # self.West = West.copy()

            # Calculate the coefficient of normal/ annular Zernike polynomials
            if (self.parameter["compMode"] == "zer"):
                zc = ZernikeMaskedFit(West, inst.xSensor, inst.ySensor, numTerms, self.pMask, zobsR)
            else:
                zc = np.zeros(numTerms)

        elif (PoissonSolver == "exp"):

            # Use the integration method by serial expansion to solve the Poisson's equation

            # Calculate I0 and dI
            I0, dI = self.__getdIandI(I1, I2)

            # Get the x, y coordinate in mask. The element outside mask is 0.
            xSensor = inst.xSensor*self.cMask
            ySensor = inst.ySensor*self.cMask

            # Create the F matrix and Zernike-related matrixes
            F = np.zeros(numTerms)
            dZidx = np.zeros([numTerms, sensorSamples, sensorSamples])
            dZidy = dZidx.copy()

            zcCol = np.zeros(numTerms)
            for ii in range(int(numTerms)):

                # Calculate the matrix for each Zk related component
                # Set the specific Zk cofficient to be 1 for the calculation
                zcCol[ii] = 1

                F[ii] = np.sum(dI*ZernikeAnnularEval(zcCol, xSensor, ySensor, zobsR))*dOmega
                dZidx[ii, :, :] = ZernikeAnnularGrad(zcCol, xSensor, ySensor, zobsR, "dx")
                dZidy[ii, :, :] = ZernikeAnnularGrad(zcCol, xSensor, ySensor, zobsR, "dy")

                # Set the specific Zk cofficient back to 0 to avoid interfering other Zk's calculation
                zcCol[ii] = 0

            # Calculate Mij matrix, need to check the stability of integration and symmetry later
            Mij = np.zeros([numTerms, numTerms])
            for ii in range(numTerms):
                for jj in range(numTerms):
                    Mij[ii, jj] = np.sum( I0*(dZidx[ii, :, :].squeeze()*dZidx[jj, :, :].squeeze() +
                                              dZidy[ii, :, :].squeeze()*dZidy[jj, :, :].squeeze()) )
            Mij = dOmega/(apertureDiameter/2.)**2 * Mij

            # Calculate dz
            focalLength = inst.parameter["focalLength"]
            offset = inst.parameter["offset"]
            dz = 2*focalLength*(focalLength-offset)/offset

            # Define zc
            zc = np.zeros(numTerms)

            # Consider specific Zk terms only
            idx = [x - 1 for x in self.parameter["ZTerms"]]

            # Solve the equation: M*W = F => W = M^(-1)*F
            zc_tmp = np.linalg.lstsq(Mij[:, idx][idx], F[idx])[0]/dz
            zc[idx] = zc_tmp

            # Estimate the wavefront surface based on z4 - z22
            # z0 - z3 are set to be 0 instead
            West = ZernikeAnnularEval(np.concatenate(([0, 0, 0], zc[3:])), xSensor, ySensor, zobsR)

        return zc, West

    def __createSignal(self, inst, I1, I2, cliplevel):
        """

        Calculate the wavefront singal for "fft" to use in solving the Poisson's equation.

        Need to discuss the method to define threshold and discuss to use np.median() instead.
        Need to discuss why the calculation of I0 is different from "exp".

        Arguments:
            inst {[Instrument]} -- Instrument to use.
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
            cliplevel {[float]} -- Parameter to determine the threshold of calculating I0.

        Returns:
            [float] -- Approximated wavefront signal.
        """

        # Check the condition of images
        I1image, I2image = self.__checkImageDim(I1, I2)

        # Wavefront signal S=-(1/I0)*(dI/dz) is approximated to be -(1/delta z)*(I1-I2)/(I1+I2)
        num = I1image - I2image
        den = I1image + I2image

        # Define the effective minimum central signal element by the threshold ( I0=(I1+I2)/2 )

        # Calculate the threshold
        pixelList = den * self.cMask
        pixelList = pixelList[pixelList!=0]

        low = pixelList.min()
        high = pixelList.max()
        medianThreshold = (high-low)/2. + low

        # Define the effective minimum central signal element
        den[den < medianThreshold*cliplevel] = 1.5*medianThreshold

        # Calculate delta z = f(f-l)/l, f: focal length, l: defocus distance of the image planes
        focalLength = inst.parameter["focalLength"]
        offset = inst.parameter["offset"]
        deltaZ = focalLength*(focalLength-offset)/offset

        # Calculate the wavefront signal. Enforce the element outside the mask to be 0.
        den[den==0] = np.inf

        # Calculate the wavefront signal
        S = num/den/deltaZ

        # Extend the dimension of signal to the order of 2 for "fft" to use
        padDim = self.parameter["padDim"]
        Sout = padArray(S, padDim)*self.cMaskPad

        return Sout

    def __getdIandI(self, I1, I2):
        """

        Calculate the central image and differential image to be used in the serial expansion
        method. It is noted that the images are assumed to be co-center already. And the intra-/
        extra-focal image can overlap with one another after the rotation of 180 degree.

        Arguments:
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.

        Returns:
            [float] -- Image data of I0.
            [float] -- Differential image (dI) of I0.
        """

        # Check the condition of images
        I1image, I2image = self.__checkImageDim(I1, I2)

        # Calculate the central image and differential iamge
        I0 = (I1image+I2image)/2
        dI = I2image-I1image

        return I0, dI

    def __checkImageDim(self, I1, I2):
        """

        Check the dimension of images. It is noted that the I2 image is rotated by 180
        degree.
        Need to check the reason of rotation. Is it because the I2 is assusmed to
        be extra image and rotated by 180 degree already in Image.py?

        Arguments:
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.

        Returns:
            [float] -- Defocal images. It is noted that the I2 image is rotated by
                       180 degree.

        Raises:
            Exception -- Check the dimension of images is n by n or not.
            Exception -- Check two defocal images have the same size or not.
        """

        # Check the condition of images
        m1, n1 = I1.image.shape
        m2, n2 = I2.image.shape

        if (m1 != n1 or m2 != n2):
            raise Exception("Image is not square.")

        if (m1 != m2 or n1 != n2):
            raise Exception("Images do not have the same size.")

        # Define I1
        I1image = I1.image

        # Rotate the image by 180 degree through rotating two times of 90 degree
        I2image = np.rot90(I2.image, k=2)

        return I1image, I2image

    def __makeMasterMask(self, I1, I2, poissonSolver=None):
        """

        Calculate the common mask of defocal images.

        Arguments:
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.

        Keyword Arguments:
            poissonSolver {[string]} -- Algorithm to solve the Poisson's equation. If the "fft" is
                                        used, the mask dimension will be extended to the order of 2
                                        for the "fft" to use.
        """

        # Get the overlap region of mask for intra- and extra-focal images. This is to avoid the
        # anormalous signal due to difference in vignetting.
        self.pMask = I1.pMask*I2.pMask
        self.cMask = I1.cMask*I2.cMask

        # Change the dimension of image for fft to use
        if (poissonSolver == "fft"):
            padDim = self.parameter["padDim"]
            self.pMaskPad = padArray(self.pMask, padDim)
            self.cMaskPad = padArray(self.cMask, padDim)

    def __applyI1I2pMask(self, I1, I2):
        """

        Correct the defocal images if I1 and I2 are belong to different sources.

        (There is a problem for this actually. If I1 and I2 come from different sources, what should
        the correction of TIE be? At this moment, the fieldX and fieldY of I1 and I2 should be different.
        And the sources are different also.)

        Arguments:
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.

        Returns:
            [Image] -- Corrected images.
        """

        # Get the overlap region of images and do the normalization.
        if (I1.fieldX != I2.fieldX or I1.fieldY != I2.fieldY):

            # Get the overlap region of image
            I1.updateImage(I1.image*self.pMask)

            # Rotate the image by 180 degree through rotating two times of 90 degree
            I2.updateImage(I2.image*np.rot90(self.pMask, 2))

            # Do the normalization of image.
            I1.updateImage(I1.image/np.sum(I1.image))
            I2.updateImage(I2.image/np.sum(I2.image))

        # Return the correct images. It is noted that there is no need of vignetting correction.
        # This is after masking already in __singleItr() or itr0().
        return I1, I2

    def __reset(self, I1, I2):
        """

        Reset the iteration time of outer loop and defocal images.

        Arguments:
            I1 {[Image]} -- Intra- or extra-focal image.
            I2 {[Image]} -- Intra- or extra-focal image.
        """

        # Reset the current iteration time to 0
        self.currentItr = 0

        # Show the reset information
        if (self.debugLevel >= 3):
            print("Resetting images: I1 and I2")

        # Determine to reset the images or not based on the existence of
        # the attribute: Image.image0. Only after the first run of
        # inner loop, this attribute will exist.
        try:
            # Reset the images to the first beginning
            I1.updateImage(I1.image0.copy())
            I2.updateImage(I2.image0.copy())

            # Show the information of resetting image
            if (self.debugLevel >= 3):
                print("Resetting images in inside.")

        except AttributeError:
            # Show the information of no image0
            if (self.debugLevel >= 3):
                print("Image0 = None. This is the first time to run the code.")

            pass

    def outZer4Up(self, unit="nm", filename=None, showPlot=False):
        """

        Put the coefficients of normal/ annular Zernike polynomials on terminal
        or file ande show the image if it is needed.

        Keyword Arguments:
            unit {[string]} -- Unit of the coefficients of normal/ annular Zernike polynomials.
                               It can be m, nm, or um. (default: {"nm"})
            filename {[string]} -- Name of output file. (default: {None})
            showPlot {[bool]} -- Decide to show the plot or not. (default: {False})
        """

        # List of Zn,m
        Znm = ["Z0,0", "Z1,1", "Z1,-1", "Z2,0", "Z2,-2", "Z2,2",  "Z3,-1", "Z3,1", "Z3,-3", "Z3,3", 
               "Z4,0", "Z4,2", "Z4,-2", "Z4,4", "Z4,-4", "Z5,1", "Z5,-1", "Z5,3", "Z5,-3", "Z5,5", 
               "Z5,-5", "Z6,0"]

        # Decide the format of z based on the input unit (m, nm, or um)
        if (unit == "m"):
            z = self.zer4UpNm*1e-9
        elif (unit == "nm"):
            z = self.zer4UpNm
        elif (unit == "um"):
            z = self.zer4UpNm*1e-3
        else:
            print("Unknown unit: %s" % unit)
            print("Unit options are: m, nm, um")
            return

        # Write the coefficients into a file if needed.
        if (filename is not None):
            f = open(filename, "w")
        else:
            f = sys.stdout

        for ii in range(4, len(z)+4):
            f.write("Z%d (%s)\t %8.3f\n" % (ii, Znm[ii-1], z[ii-4]))

        # Close the file
        if (filename is not None):
            f.close()

        # Show the plot
        if (showPlot):
            plt.figure()

            x = range(4, len(z) + 4)
            plt.plot(x, z, marker="o", color="r", markersize=10)
            plt.xlabel("Zernike Index")
            plt.ylabel("Zernike coefficient (%s)" % unit)
            plt.grid()
            plt.show()

class AlgorithmTest(unittest.TestCase):
    """
    Test functions in Algorithm.
    """

    def setUp(self):

        # Get the path of module
        self.modulePath = getModulePath()

        # Define the instrument folder
        instruFolder = os.path.join(self.modulePath, "algoData", "cwfs", "instruData")

        # Define the algorithm folder
        algoFolderPath = os.path.join(self.modulePath, "algoData", "cwfs", "algo")

        # Define the instrument name
        instruName = "lsst"

        # Define the algorithm being used: "exp" or "fft"
        useAlgorithm = "fft"

        # Define the image folder and image names
        # Image data -- Don't know the final image format.
        # It is noted that image.readFile inuts is based on the txt file
        imageFolderPath = os.path.join(self.modulePath, "test", "testImages", "LSST_NE_SN25")
        intra_image_name = "z11_0.25_intra.txt"
        extra_image_name = "z11_0.25_extra.txt"

        # Define fieldXY: [1.185, 1.185] or [0, 0]
        # This is the position of donut on the focal plane in degree
        fieldXY = [1.185, 1.185]

        # Define the optical model: "paraxial", "onAxis", "offAxis"
        self.opticalModel = "offAxis"

        # Image files Path
        intra_image_file = os.path.join(imageFolderPath, intra_image_name)
        extra_image_file = os.path.join(imageFolderPath, extra_image_name)

        # Theree is the difference between intra and extra images
        # I1: intra_focal images, I2: extra_focal Images
        # self.I1 = Image.Image()
        # self.I2 = Image.Image()

        self.I1 = CompensationImageDecorator()
        self.I2 = CompensationImageDecorator()

        self.I1.setImg(fieldXY, imageFile=intra_image_file, atype="intra")
        self.I2.setImg(fieldXY, imageFile=extra_image_file, atype="extra")

        self.inst = Instrument(instruFolder)
        self.inst.config(instruName, self.I1.sizeinPix)

    def testExp(self):

        # Define the algorithm folder
        algoFolderPath = os.path.join(self.modulePath, "algoData", "cwfs", "algo")

        # Define the algorithm being used: "exp" or "fft"
        useAlgorithm = "exp"

        # Define the algorithm to be used.
        algo = Algorithm(algoFolderPath)
        algo.config(useAlgorithm, self.inst, debugLevel=3)
        algo.setDebugLevel(0)
        self.assertEqual(algo.debugLevel, 0)

        # Test functions: itr0() and nextItr()
        algo.itr0(self.inst, self.I1, self.I2, self.opticalModel)
        tmp1 = algo.zer4UpNm
        algo.nextItr(self.inst, self.I1, self.I2, self.opticalModel, nItr=2)
        algo.itr0(self.inst, self.I1, self.I2, self.opticalModel)
        tmp2 = algo.zer4UpNm

        difference = np.sum(np.abs(tmp1-tmp2))
        self.assertEqual(difference, 0)

        # Run it
        algo.runIt(self.inst, self.I1, self.I2, self.opticalModel, tol=1e-3)

        # Check the value
        Zk = algo.zer4UpNm
        self.assertEqual(int(Zk[7]), -192)

        # Reset and check the calculation again
        fieldXY = [self.I1.fieldX, self.I1.fieldY]
        self.I1.setImg(fieldXY, image=self.I1.image0, atype=self.I1.atype)
        self.I2.setImg(fieldXY, image=self.I2.image0, atype=self.I2.atype)
        algo.reset()
        algo.runIt(self.inst, self.I1, self.I2, self.opticalModel, tol=1e-3)
        Zk = algo.zer4UpNm
        self.assertEqual(int(Zk[7]), -192)

    def testFFT(self):

        # Define the algorithm folder
        algoFolderPath = os.path.join(self.modulePath, "algoData", "cwfs", "algo")

        # Define the algorithm being used: "exp" or "fft"
        useAlgorithm = "fft"

        # Define the algorithm to be used.
        algo = Algorithm(algoFolderPath)
        algo.config(useAlgorithm, self.inst, debugLevel=0)

        # Run it
        algo.runIt(self.inst, self.I1, self.I2, self.opticalModel, tol=1e-3)

        # Check the value
        Zk = algo.zer4UpNm
        self.assertEqual(int(Zk[7]), -192)

if __name__ == "__main__":

    # Do the unit test
    unittest.main()
