# Wavefront Estimation Pipeline (WEP)

*This module is used to calculate the wavefront error in annular Zernike polynomials up to 22 terms (z4-z22) based on the intra- and extra-focal images in the large synoptic survey telescope (LSST). The main idea is to use the transport of intensity (TIE) and assume the change of intensity only comes from the wavefront error.*

## 1. Version History

*Version 1.0*
<br/>
*Finish the WEP in totally ideal condition.*
<br/>
*Version 1.01*
<br/>
*Integrate the DM cmd task and implement the high-level WEPController class.*

*Author: Te-Wei Tsai*
*Date: 4-3-2018*

## 2. Platform

- *python: 3.6.2*
- *scientific pipeline: v14*

## 3. Needed Package

- *lsst_sims*
- *lsst_distrib*
- *obs_lsstSim - syseng3 branch*
- *numpy*
- *scipy*
- *astropy*
- *matplotlib*
- *cython*
- *scikit-image*

## 4. Compile cwfs
* To compile the code, at the path of cwfs in terminal, execute "python builder/setup.py build_ext --build-lib python/lsst/ts/wep/cwfs/lib". 

## 5. Setup Tag and Use the obs_lsstSim

- *0. Install the lsst_sims by "eups distrib install lsst_sims -t sims".*
- *1. Install the lsst_distrib by "eups distrib install lsst_distrib -t sims".*
- *2. Clone the repository (e.g. obs_lsstSim) in some other directory. To import PhoSim simulated images, the branch of syseng3 is needed.*
- *3. Declare that clone to eups by cd'ing into the directory and running "eups declare -r . package_name my_version -t my_tag". EUPS is restrictive about what names are valid for versions and tags. Your username is always legal, so "eups declare -r . obs_lsstSim ttsai -t ttsai" should work.*
- *4. Setup the package. You will need to use something like "setup sims_catUtils -t ttsai -t sims".  That way, any package that does not have a "ttsai" tag available will be setup with the "sims" tag.*
- *5. Use "scons" under the repository to build it.*

## 6. DM Command Line Task (obs_lsstSim)

*0. Download the obs_lsstSim. It is noted that the user does not need to follow the readme on this repo. Instead, we use the API in syseng3 branch to do this.*
<br>
The repository can be downloaded at: https://github.com/lsst/obs_lsstSim/tree/master/python/lsst/obs/lsstSim
<br/>

*1. Make the input repository*
<br/>
mkdir input
<br/>
echo 'lsst.obs.lsstSim.LsstSimMapper' > input/_mapper
<br/>
*2. Ingest the images*
<br/>
ingestSimImages.py input ../Raw/lsst_*.fits
<br/>
*3. Make and ingest the calibration products. The next two steps are time consuming and really only need to be done once*.
<br/>
makeGainImages.py
<br/>
ingestCalibs.py input R*.fits --validity 99999 --output input
<br/>
*4. Process the images*
<br/>
processSimCcd.py input --id --output output

## 7. Use of Module

*1. Setup the DM environment:*
<br/>
source $path_of_lsst_scientific_pipeline/loadLSST.bash
<br/>
setup sims_catUtils -t $user_defined_tag -t sims
(e.g. setup sims_catUtils -t ttsai -t sims)

*2. Setup the WEP environment:*
<br/>
export PYTHONPATH=$PYTHONPATH:$path_to_ts_tcs_wep_python
<br/>
(e.g. export PYTHONPATH=$PYTHONPATH:/home/ttsai/Document/stash/ts_tcs_wep/python)

*3. Connect to fatboy server:*
<br/>
ssh -i $Position_of_SSH_key -L 51433:fatboy.phys.washington.edu:1433 simsuser@gateway.astro.washington.edu
<br/>
e.g. 
<br/>
ssh -i /home/ttsai/.ssh/fatboy -L 51433:fatboy.phys.washington.edu:1433 simsuser@gateway.astro.washington.edu
<br/>
<br/>
Keep this terminal open for the connection.

## 8. Integrate with SAL

*Some environment paths defined in ts_sal/setup.env need to be modified to use lsst stack with SAL.*

*Need to setup the following path variables: LSST_SDK_INSTALL, OSPL_HOME, PYTHON_BUILD_VERSION, and PYTHON_BUILD_LOCATION.*

*1. PYTHON_BUILD_LOCATION=$lsst_stack_python_directory. e.g. PYTHON_BUILD_LOCATION=/home/ttsai/Document/lsst14/python/miniconda3-4.3.21*

*2. In ts_sal/setup.env, use 'LD_LIBRARY_PATH=
${LD_LIBRARY_PATH}:${SAL_HOME}/lib' instead of 'LD_LIBRARY_PATH=${SAL_HOME}/lib'.*

## 9. SAL XML Model

*The SAL xml model are in the 'sal_interfaces' of ts_xml repository. The branch used is the develop branch. The CSC keywords are 'tcsOfc' and 'tcsWEP' for active optics to use. The xml files can be found in the related directory. The way to generate the SAL py libraries can follow the ts_sal manual.*

## 10. Content

*This module contains the following classes:*

- **SciWFDataCollector**: Ingest the PhoSim amplifier images, and generate and ingest the fake flat calibration products based on the DM cmd task.
- **WFDataCollector**: Accommodate the PhoSim simulated image contains the sky and calibration products (bias, dark current, and flat dome light) into the data butler format. The registry repository will be updated if it is necessary.
- **SciIsrWrapper**: Do the ISR and assemble the CCD images based on the DM cmd task.
- **IsrWrapper**: Do the ISR by using DM ISR library directly. The calibration products of bias, dark current, and flat dome light are used.
- **EimgIsrWrapper**: Simulate the post-ISR image by using the electronic image generated by PhoSim. This interface keeps the same as IsrWrapper.
- **LocalDatabaseDecorator**: Insert and delete the data from the local data base that is used by the SourceSelector.
- **SourceSelector**: Query the bright star catalog (BSC) in University of Washington (UW) to select the available target to do the WEP. If the star data is in the local database already, the query is also available.
- **SourceProcessor**: Process the post-ISR images to get the clean star images with measured optical coordinate (field x, y). The deblending algorithm is used to get the single target star image if the neighboring stars exist.
- **WFEstimator**: Calculate the wavefront error in annular Zernike polynomials up to 22 terms based on the defocal star donut images.
- **Middleware**: Communicate with subsystems by software abstraction layer (SAL).
- **DefocalImage**: Container for the defocal images.
- **DonutImage**: Container for the donut images.
- **WEPController**: High level class to use the WEP package.
- **Utility**: Utility functions used in WEP.

## 11. Example Script

- **doCmdCalib.py**: Generate the calibration products and do the ingestion. This step is time-consuming and only needs to do once.
- **wfsCommu.py**: Use the WEPController to issue the event and publish the telemetry.
- **calcWfsErrAmp.py**: Ingest the amplifier images (LSST central raft), do the ISR by DM cmd task, do the source selection, and calculate the wavefront error.
- **calcWfsErrEimgComcam.py**: Ingest the ComCam eimages, do the fake ISR, do the source selection, and calculate the wavefront error.
- **calcWfsErrEimgWfs.py**: Get the corner WFS eimages (data butler does not support this at this moment), do the source selection, and calculate the wavefront error.

## 12. Target for Future Release

- *Integration of WEP and PhoSim is not done yet. There might be some inconsistency of coordinate among PhoSim, camera control system (CCS), and DM.*
- *TIE is used as the main algorithm, which is based on the single source. However, for the LSST normal case, this is not true. The initial idea here is to normalize the intensities of multiple sources.*
- *No boundary consideration of TIE studied.*
- *The use of instrument signature removal (ISR) in WEP traces to data management (DM) ISR library, which needs to customize the details/ strategies in the future release.*
- *The deblending algorithm assumes the neighboring stars have the same optical condition as the bright star. This algorithm can only handle one neighboring star that has certain magnitude and distance compared with the bright star.*
- *The algorithm to calculate the centroid of star needs a clean background.*
- *No system error is considered.*
- *No image quality determination included.*
- *No robust signal-to-noise ratio (SNR) calculation included.*
- *No master donut images by migration included.*
- *No vignette correction included.*
- *World coordinate system (WCS) is based on the focal plane with the parallax model. However, the defocal images are used in TIE. The difference and compensation between real and calculated pixel positions are not considered yet.*
- *The reliability of BSC in University of Washington (UW) is not verified.*
- *The local BSC database is not constructed. Need to use the Scheduler to give a reasonable survey route to minimize the calculation time. Another choice is to use SkyCoord() in Astropy. The ref is at: "http://docs.astropy.org/en/stable/api/astropy.coordinates.SkyCoord.html".*
- *The mechanism to update the BSC is not included.*
- *No statistics/ strategy of selecting wavefront sensors on full-focal plane of LSST camera included.*
- *The calculation time is much longer than the spec (14 sec).*
- *The pipeline framework (e.g. luigi) and parallel calculation are not included.*
- *The data collection from data acquisition (DAQ) is not included.*
- *The commissioning camera (ComCam) mapper is mocked based on the central raft of LSST mapper.*
- *Update the annular Zernike polynomials to Z37.*
