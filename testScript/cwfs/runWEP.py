# -*- coding: utf-8 -*-

import os
import sys
from lsst.ts.wep.cwfs import Instrument, Algorithm, CompensationImageDecorator
from lsst.ts.wep.cwfs.Tool import plotImage
from lsst.ts.wep.Utility import getModulePath

def runWEP(instruFolder, algoFolderPath, instruName, useAlgorithm, imageFolderPath, 
           intra_image_name, extra_image_name, fieldXY, opticalModel, showFig=False, 
           showConf=False, filename=None):
    """
    
    Calculate the coefficients of normal/ annular Zernike polynomials based on the provided
    instrument, algorithm, and optical model.
    
    Arguments:
        instruFolder {[string]} -- Path to instrument folder.
        algoFolderPath {[string]} -- Path to algorithm folder.
        instruName {[string]} -- Instrument name. It is "lsst" in the baseline.
        useAlgorithm {[string]} -- Algorithm to solve the Poisson's equation in the transport 
                                   of intensity equation (TIE). It can be "fft" or "exp" here. 
        imageFolderPath {[string]} -- Path to image folder.
        intra_image_name {[string]} -- File name of intra-focal image.
        extra_image_name {[string]} -- File name of extra-focal image.
        fieldXY {[float]} -- Position of donut on the focal plane in degree for intra- and extra-focal
                             images.
        opticalModel {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
        showFig{[bool]} -- Show the wavefront image and compenstated image or not. (default: {False})
        showConf{[bool]} -- Decide to show the configuration or not. (default: {False})
        filename{[string]} -- Name of output file. (default: {None})
    
    Returns:
        [float] -- Coefficients of Zernike polynomials (z4 - z22).
    """
    
    # Image files Path  
    intra_image_file = os.path.join(imageFolderPath, intra_image_name)
    extra_image_file = os.path.join(imageFolderPath, extra_image_name)

    # There is the difference between intra and extra images
    # I1: intra_focal images, I2: extra_focal Images
    I1 = CompensationImageDecorator.CompensationImageDecorator()
    I2 = CompensationImageDecorator.CompensationImageDecorator()

    I1.setImg(fieldXY[0], imageFile=intra_image_file, atype="intra")
    I2.setImg(fieldXY[1], imageFile=extra_image_file, atype="extra")

    # Set the instrument
    inst = Instrument.Instrument(instruFolder)
    inst.config(instruName, I1.sizeinPix)

    # Define the algorithm to be used.
    algo = Algorithm.Algorithm(algoFolderPath)
    algo.config(useAlgorithm, inst, debugLevel=0)

    # Plot the original wavefront images
    if (showFig):
        plotImage(I1.image, title="intra image")
        plotImage(I2.image, title="extra image")

    # Run it
    algo.runIt(inst, I1, I2, opticalModel, tol=1e-3)

    # Show the Zernikes Zn (n>=4)
    algo.outZer4Up(showPlot=False)

    # Plot the final conservated images and wavefront
    if (showFig):
        plotImage(I1.image, title="Compensated intra image")
        plotImage(I2.image, title="Compensated extra image")

        # Plot the Wavefront
        plotImage(algo.wcomp, title="Final wavefront")
        plotImage(algo.wcomp, title="Final wavefront with pupil mask applied", mask=algo.pMask)

    # Show the information of image, algorithm, and instrument
    if (showConf):
        __outParam(algo, inst, I1, I2, opticalModel, filename)
    
    # Return the Zernikes Zn (n>=4)
    return algo.zer4UpNm

def __outParam(algo, inst, I1, I2, opticalModel, filename=None):
    """
    
    Put the information of images, instrument, and algorithm on terminal or file.
    
    Arguments:
        algo {[Algorithm]} -- Algorithm to solve the Poisson's equation in the transport 
                              of intensity equation (TIE). 
        inst {[Instrument]} -- Instrument to use.
        I1 {[Image]} -- Intra- or extra-focal image.
        I2 {[Image]} -- Intra- or extra-focal image.
        opticalModel {[string]} -- Optical model. It can be "paraxial", "onAxis", or "offAxis".
    
    Keyword Arguments:
        filename {[string]} -- Name of output file. (default: {None})
    """

    # Write the parameters into a file if needed.
    if (filename is not None):
        fout = open(filename, "w")
    else:
        fout = sys.stdout

    # Write the information of image and optical model
    fout.write("intra image: \t %s \t field in deg =(%6.3f, %6.3f)\n" %
               (I1.name, I1.fieldX, I1.fieldY))
    fout.write("extra image: \t %s \t field in deg =(%6.3f, %6.3f)\n" %
               (I2.name, I2.fieldX, I2.fieldY))
    fout.write("Using optical model:\t %s\n" % opticalModel)
    
    # Read the instrument file
    __readConfigFile(fout, inst, "instrument")

    # Read the algorithm file
    __readConfigFile(fout, algo, "algorithm")

    # Close the file
    if (filename is not None):
        fout.close()

def __readConfigFile(fout, config, configName):
    """
    
    Read the configuration file
    
    Arguments:
        fout {[file]} -- File instance.
        config {[metadata]} -- Instance of configuration. It is Instrument or Algorithm here.
        configName {[string]} -- Name of configuration.
    """

    # Create a new line
    fout.write("\n")
    
    # Open the file
    fconfig = open(config.filename)
    fout.write("---" + configName + " file: --- %s ----------\n" % config.filename)
    
    # Read the file information
    iscomment = False
    for line in fconfig:
        line = line.strip()
        if (line.startswith("###")):
            iscomment = ~iscomment
        if (not(line.startswith("#")) and (not iscomment) and len(line) > 0):
            fout.write(line + "\n")

    # Close the file
    fconfig.close()

if __name__ == "__main__":

    # Get the path of module
    modulePath = getModulePath()
        
    # Define the instrument folder
    instruFolder = os.path.join(modulePath, "algoData", "cwfs", "instruData")

    # Define the algorithm folder
    algoFolderPath = os.path.join(modulePath, "algoData", "cwfs", "algo")
    
    # Define the instrument name
    instruName = "lsst"

    # Define the algorithm being used: "exp" or "fft"
    useAlgorithm = "fft"
    
    # Define the image folder and image names
    # Image data -- Don't know the final image format. 
    # It is noted that image.readFile inuts is based on the txt file
    imageFolderPath = os.path.join(modulePath, "test", "testImages", "LSST_NE_SN25")
    intra_image_name = "z11_0.25_intra.txt"
    extra_image_name = "z11_0.25_extra.txt"
    
    # Define fieldXY: [1.185, 1.185] or [0, 0]
    # This is the position of donut on the focal plane in degree
    fieldXY = [1.185, 1.185]
    
    # Define the optical model: "paraxial", "onAxis", "offAxis"
    opticalModel = "offAxis"
    
    # Run the WEP and show the result
    zer4UpNm = runWEP(instruFolder, algoFolderPath, instruName, useAlgorithm, imageFolderPath, 
                      intra_image_name, extra_image_name, [fieldXY, fieldXY], opticalModel, 
                      showFig=False, showConf=False)
    
    