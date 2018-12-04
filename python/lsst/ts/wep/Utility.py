import os
from pathlib import Path
import lsst.ts.wep

def getModulePath(module=lsst.ts.wep, startIdx=3, endIdx=-4):
    """
    
    Get the directory of WEP module.

    Keyword Arguments:
    	[module] -- Module.
    	[int] -- Start index. (Default: {3})
    	[int] -- End index. (Default: {-4})
    
    Returns:
        [str] -- Directory of module based on the start and end indexes.
    """

    # Get the path of module
    modulePath = '/project/activeoptics/firstdonuts/ts_tcs_wep'
    
    return modulePath

if __name__ == "__main__":
    pass
