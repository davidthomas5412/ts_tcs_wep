import os, sqlite3, unittest
import numpy as np

from lsst.ts.wep.bsc.BrightStarDatabase import BrightStarDatabase
from lsst.ts.wep.bsc.StarData import StarData
from lsst.ts.wep.Utility import getModulePath

class LocalDatabase(BrightStarDatabase):

    def connect(self, dbAdress):
        """
        
        Connects database based on the local path.
        
        Arguments:
            dbAdress {[string]} -- Path of local sqlite3 database.
        """

        self.connection = sqlite3.connect(dbAdress)
        self.cursor = self.connection.cursor()

    def printAll(self, cameraFilter):
        """
        
        Print all data based on the filter type. This is only for the debug.
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
        """

        # Print the table
        command = "SELECT * FROM BrightStarCatalog" + cameraFilter.upper()
        self.cursor.execute(command)
        result = self.cursor.fetchall()

        print(result)

    def searchSimobjdID(self, cameraFilter, listID):
        """
        
        Search data based on the simobjid. It is noted that this simobjid is not unique in 
        UW. 
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
            listID {[int]} -- simobjid list to search.
        
        Returns:
            result {[metadata]} -- Results (id, ra, decl) of search
        """

        # Search the simobjid data
        command = "SELECT id, ra, decl From BrightStarCatalog" + cameraFilter.upper() + \
                  " WHERE simobjid in (" + ', '.join(str(id) for id in listID) + ")"
        self.cursor.execute(command)
        result = self.cursor.fetchall()

        return result

    def searchRaDecl(self, cameraFilter, ra, decl):
        """
        
        Search the star id based on ra, decl.
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
            ra {[float]} -- ra in degree (0 deg - 360 deg).
            decl {[float]} -- decl in degree (-90 deg - 90 deg).
        
        Returns:
            [int] -- Star ID in local databse.
        """

        # Compare ra and decl to see the existance of star in database
        command = "SELECT id FROM BrightStarCatalog" + cameraFilter.upper() + \
                  " WHERE ra = %f AND decl = %f" 
        query = command % (ra, decl)
        self.cursor.execute(query)
        
        return self.cursor.fetchall()

    def insertData(self, cameraFilter, neighborStarMap):
        """
        
        Insert new star data into the local database.  
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
            neighborStarMap {[NeighboringStar]} -- Information of neighboring stars.
        """

        # List of bright star
        brightStarList = list(neighborStarMap.SimobjID)

        # Check the existed bright star data based on ra and decl
        existIdList = []
        for ii in range(len(brightStarList)):
            raDec = neighborStarMap.RaDecl[brightStarList[ii]]
            if (self.searchRaDecl(cameraFilter,raDec[0],raDec[1])):
                existIdList.append(brightStarList[ii])

        # Collect the lists not in database yet. 
        # remainIDList is the bright star list. And allStarList is the list 
        # contains the bright stars and related neighboring stars.
        remainIdList = []
        allStarList = []
        for id in brightStarList:
            if id not in existIdList:
                remainIdList.append(id)
                allStarList.append(id)
                for starID in neighborStarMap.SimobjID[id]:
                    # Make sure the starID is not in the allStarList yet
                    if starID not in allStarList:
                        allStarList.append(starID)
       
        # Insert the star data to local data base
        for simobjID in allStarList:

            # Insert data
            command = "INSERT INTO BrightStarCatalog" + cameraFilter.upper() + \
                      " (simobjid, ra, decl, " + cameraFilter + "mag, bright_star) " + \
                      "VALUES (?, ?, ?, ?, ?)"

            raDec = neighborStarMap.RaDecl[simobjID]
            
            if (cameraFilter == self.FilterU):
                mag = neighborStarMap.LSSTMagU[simobjID]
            elif (cameraFilter == self.FilterG):
                mag = neighborStarMap.LSSTMagG[simobjID]
            elif (cameraFilter == self.FilterR):
                mag = neighborStarMap.LSSTMagR[simobjID]
            elif (cameraFilter == self.FilterI):
                mag = neighborStarMap.LSSTMagI[simobjID]
            elif (cameraFilter == self.FilterZ):
                mag = neighborStarMap.LSSTMagZ[simobjID]
            elif (cameraFilter == self.FilterY):
                mag = neighborStarMap.LSSTMagY[simobjID]

            if simobjID in remainIdList:
                brightStar = True
            else:
                brightStar = False

            task = (int(simobjID), raDec[0], raDec[1], mag, brightStar)

            self.cursor.execute(command, task)

        # Commit the change to database
        self.connection.commit()

    def updateData(self, cameraFilter, listID, listOfItemToChange, listOfNewValue):
        """
        
        Update data based on the id.
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
            listID {[int]} -- ID list to change.
            listOfItemToChange {[string]} -- Item list (simobjid, ra, decl, mag, bright_star) to change.
            listOfNewValue {[valueType]} -- New value list.

        Raises:
            ValueError -- Not the correct type to update.
        """

        # Check the item can be updated or not
        for item in listOfItemToChange:
            if item not in ("simobjid", "ra", "decl", "mag", "bright_star"):
                raise ValueError("'%s' can not be updated." % item)

        # Update data based on the id
        for ii in range(len(listID)):

            # Check the item is "mag" or not. If it is "mag", give the related filter information.
            itemToChange = listOfItemToChange[ii]
            if (itemToChange == "mag"):
                itemToChange = cameraFilter + itemToChange

            # Give the SQL command
            command = "UPDATE BrightStarCatalog" + cameraFilter.upper() + \
                      " SET " + itemToChange + "=" + str(listOfNewValue[ii]) + \
                      " WHERE id=?"  
            self.cursor.execute(command, (listID[ii],))

        # Commit the change to database
        self.connection.commit()

    def deleteData(self, cameraFilter, listID):
        """
        
        Delete data based on the id.
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
            listID {[int]} -- ID list to delete.
        """

        # Delete the data
        for id in listID:       
            command = "DELETE FROM BrightStarCatalog" + cameraFilter.upper() + " WHERE id=?"
            self.cursor.execute(command, (id,))

        # Commit the change to database
        self.connection.commit()

    def getAllId(self, cameraFilter):
        """
        
        Get all ID in the database.
        
        Arguments:
            cameraFilter {[string]} -- Filter type of camera: u, g, r, i, z, y.
        
        Returns:
            [int] -- ID list
        """

        # Print the table
        command = "SELECT id FROM BrightStarCatalog" + cameraFilter.upper()
        self.cursor.execute(command)
        listID = self.cursor.fetchall()
        return np.asarray(listID).squeeze().tolist()

class LocalDatabaseTest(unittest.TestCase):
    """
    Test the function of LocalDatabase.
    """

    # Camera Filter
    cameraFilter = "g"

    # Neighboring stars
    neighboringStar = None

    def setUp(self):

        # Get the path of module
        modulePath = getModulePath()

        # Local database setting
        dbAdress = os.path.join(modulePath, "test", "bsc.db3")
        
        # Set up local database
        self.localDatabase = LocalDatabase()
        self.localDatabase.connect(dbAdress)

        # Set up neighboring star map
        stars = StarData([123, 456, 789], [0.1, 0.2, 0.3], [2.1, 2.2, 2.3], [2.0, 3.0, 4.0], 
                         [2.0, 3.0, 4.0], [2.0, 3.0, 4.0], [2.0, 3.0, 4.0], [2.0, 3.0, 4.0], 
                         [2.0, 3.0, 4.0])
        stars.populateRAData([value*10 for value in stars.RA])
        stars.populateDeclData([value*10 for value in stars.Decl])
        self.neighboringStar = stars.getNeighboringStar([0], 3, self.cameraFilter, 99)

    def tearDown(self):
        # Disconnect database
        self.localDatabase.disconnect()
        
    def testLocalDatabase(self):

        localTableName = "BrightStarCatalog" + self.cameraFilter.upper()

        # Test to add data
        self.localDatabase.insertData(self.cameraFilter, self.neighboringStar)
        id = self.localDatabase.searchRaDecl(self.cameraFilter, 0.1, 2.1)
        self.assertEqual(len(id), 1)

        # Test to add the repeated data
        numId = self.localDatabase.getAllId(self.cameraFilter)
        self.localDatabase.insertData(self.cameraFilter, self.neighboringStar)
        newNumId = self.localDatabase.getAllId(self.cameraFilter)
        self.assertEqual(len(numId), len(newNumId))

        # Test to search simobjdID
        simobjid = self.localDatabase.searchSimobjdID(self.cameraFilter, [123, 456, 789])
        self.assertEqual(len(simobjid), 3)

        # Test to update data
        self.localDatabase.updateData(self.cameraFilter, [simobjid[0][0], simobjid[1][0], simobjid[2][0]], 
                                      ["ra", "ra", "ra"], [1.0, 2.0, 3.0])
        oldDataId = self.localDatabase.searchRaDecl(self.cameraFilter, 0.2, 2.2)
        newDataId = self.localDatabase.searchRaDecl(self.cameraFilter, 2.0, 2.2)
        self.assertEqual(len(oldDataId), 0)
        self.assertEqual(len(newDataId), 1)

        # Test to delete data
        self.localDatabase.deleteData(self.cameraFilter, [simobjid[0][0], simobjid[1][0], simobjid[2][0]])
        newNumId = self.localDatabase.getAllId(self.cameraFilter)
        self.assertNotEqual(numId, newNumId)

if __name__ == '__main__':

    # Do the unit test
    unittest.main()