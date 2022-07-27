import sqlalchemy as db
from sqlalchemy import select, insert, and_
from sqlalchemy.engine import CursorResult

import settings
import os
import uuid

from Schemas import Schemas
import CBSD
from core import SASREM
from SASAlgorithms import SASAlgorithms
import Server_WinnForum as WinnForum


class DatabaseController:
    ENGINE = None
    CONNECTION = None
    METADATA = None

    algorithms = SASAlgorithms()
    rem = SASREM.SASREM()

    USERS = None
    NODES = None
    GRANTS = None

    __grantRecords = []

    def __init__(self):
        self._delete_db_file()

        if settings.ENVIRONMENT == 'DEVELOPMENT':
            self._connect_to_dev_db()
        else:
            self._connect_to_prod_db()

        # Initialize tables
        self.schemas = Schemas(self.METADATA)
        self._set_tables()
        self._get_tables()

        # Create Admin User
        admin_user = {
            'secondaryUserName': settings.ADMIN_EMAIL,
            'secondaryUserEmail': settings.ADMIN_EMAIL,
            'secondaryUserPassword': settings.ADMIN_PWD,
            'deviceID': '',
            'location': ''
        }
        self.create_user(admin_user, True)

    def _connect_to_dev_db(self):
        self.ENGINE = db.create_engine(settings.DEVELOPMENT_DATABASE_URI)
        self.CONNECTION = self.ENGINE.connect()
        self.METADATA = db.MetaData()

    def _connect_to_prod_db(self):
        self.ENGINE = db.create_engine(settings.PRODUCTION_DATABASE_URI)
        self.CONNECTION = self.ENGINE.connect()
        self.METADATA = db.MetaData()

    def _execute_query(self, query):
        resultProxy: CursorResult = self.CONNECTION.execute(query)
        queryResult = resultProxy.fetchall()
        rows = [row._asdict() for row in queryResult]

        return rows

    def _delete_table(self, table: db.Table):
        table.drop(self.ENGINE)

    def _delete_all_tables(self):
        self.METADATA.drop_all(self.ENGINE)

    @staticmethod
    def _delete_db_file():
        try:
            os.remove(settings.SQLITE_FILE)
        except Exception as exception:
            print(str(exception))

    def _disconnect_from_db(self):
        self.CONNECTION.close()
        self._delete_db_file()

    # In[ --- CREATE TABLES --- ]

    def _set_tables(self):
        self.schemas.create_tables()
        self.METADATA.create_all(self.ENGINE)

    def _get_tables(self):
        self._get_secondaryUser_table()
        self._get_nodes_table()
        self._get_grants_table()

    # In[ --- USER CONTROLS --- ]

    def _get_secondaryUser_table(self):
        self.USERS = db.Table(
            settings.SECONDARY_USER_TABLE, self.METADATA, autoload=True, autoload_with=self.ENGINE
        )

    def get_secondary_users(self):
        query = select([self.USERS])
        try:
            rows = self._execute_query(query)

            return {
                'status': 1,
                'secondaryUsers': rows
            }
        except Exception as err:
            raise Exception(str(err))

    def authenticate_user(self, payload: any, isAdmin: bool):
        email = payload['username']
        password = payload['password']

        if not email or not password:
            raise Exception("Username or password not provided")

        query = select([self.USERS]).where(and_(
            self.USERS.columns.email == email,
            self.USERS.columns.password == password,
            self.USERS.columns.admin == isAdmin
        ))
        rows = self._execute_query(query)

        if len(rows) < 1:
            return {
                "status": 0
            }

        return {
            "status": 1,
            "name": rows[0]['username'],
            "id": rows[0]['username'],
            "userType": 'SU' if not rows[0]['admin'] else 'ADMIN'
        }

    def create_user(self, payload, isAdmin):
        username = payload['secondaryUserName']
        email = payload['secondaryUserEmail']
        password = payload['secondaryUserPassword']
        deviceID = payload['deviceID']
        location = payload['location']

        # Sanity Checks
        if not username:
            raise Exception("Username not provided")

        if not email:
            raise Exception("Email Address not provided")

        if not password:
            raise Exception("Password not provided")

        query = select([self.USERS]).where(self.USERS.columns.email == email)
        rows = self._execute_query(query)
        if len(rows) > 0:
            message = f"Email '{email}' already exists. Contact an administrator to recover or reset password."
            return {
                "status": 0,
                "exists": 1,
                "message": message
            }

        insertQuery = insert(self.USERS).values(
            username=username, email=email, admin=isAdmin, password=password, deviceID=deviceID, location=location
        )
        ResultProxy = self.CONNECTION.execute(insertQuery)

        rows = self._execute_query(query)
        if len(rows) < 1:
            return {
                "status": 0,
                "message": "User could not be added. Contact an administrator."
            }

        return {
            "status": 1,
            "message": "User has been added."
        }

    # In[ --- NODE CONTROLS --- ]
    
    def _get_nodes_table(self):
        self.NODES = db.Table(
            settings.NODE_TABLE, self.METADATA, autoload=True, autoload_with=self.ENGINE
        )

    def get_nodes(self):
        query = select([self.NODES])
        try:
            rows = self._execute_query(query)

            return {
                'status': 1,
                'nodes': rows
            }
        except Exception as err:
            raise Exception(str(err))

    def create_nodes(self, sid, payload):
        responseArr, assignmentArr, insertionArr = [], [], []

        for item in payload["registrationRequest"]:
            radioID = item.get('fccId', str(uuid.uuid4()))
            item['fccId'] = radioID
            # Sanity Checks
            if not radioID:
                raise Exception("Radio ID not provided")

            query = select([self.NODES]).where(and_(
                self.NODES.columns.fccId == radioID,
                self.NODES.columns.IPAddress == item['IPAddress']
            ))
            rows = self._execute_query(query)
            if len(rows) > 0:
                message = f"Node '{radioID}' already exists with the same IP Address. Node creation rollback complete"
                return {
                    "status": 0,
                    "exists": 1,
                    "message": message
                }

            insertionArr.append(item)

            radio = CBSD.CBSD(radioID, 5, radioID)
            # Flatten Structure
            location = item['location'].split(',')
            radio.latitude = location[0]
            radio.longitude = location[1]
            radio.nodeType = item["nodeType"]
            radio.minFrequency = item["minFrequency"]
            radio.maxFrequency = item["maxFrequency"]
            radio.minSampleRate = item["minSampleRate"]
            radio.maxSampleRate = item["maxSampleRate"]
            radio.mobility = item["mobility"]
            radio.id = radioID

            response = WinnForum.RegistrationResponse(radio.id, None, self.algorithms.generateResponse(0))

            if "measCapability" in item:
                cbsd = SASREM.CBSDSocket(radio.id, sid, False)
                assignmentArr.append(cbsd)
                response.measReportConfig = item["measCapability"]

            responseArr.append(response.asdict())

        try:
            self.CONNECTION.execute(self.NODES.insert(), insertionArr)
        except Exception as err:
            print(str(err))
            return {
                "status": 0,
                "message": f"Nodes could not be added due to '{str(err)}'. Contact an administrator."
            }

        # responseDict = {"registrationResponse": responseArr}

        return {
            "status": 1,
            "message": "Nodes have been added.",
            "registrationResponse": responseArr
        }, assignmentArr

    # In[ --- GRANT CONTROLS --- ]

    def get_grant_records(self):
        return self.__grantRecords

    def get_grants(self):
        query = select([self.GRANTS])
        try:
            rows = self._execute_query(query)

            return {
                'status': 1,
                'spectrumGrants': rows
            }
        except Exception as err:
            raise Exception(str(err))

    def _get_grants_table(self):
        self.GRANTS = db.Table(
            settings.GRANT_TABLE, self.METADATA, autoload=True, autoload_with=self.ENGINE
        )

    def create_grant_request(self, payload):
        responseArr, insertionArr = [], []

        for item in payload["grantRequest"]:
            query = select([self.GRANTS]).where(and_(
                self.GRANTS.columns.secondaryUserID == item['secondaryUserID'],
                self.GRANTS.columns.minFrequency == item['minFrequency'],
                self.GRANTS.columns.startTime == item['startTime']
            ))
            rows = self._execute_query(query)

            if len(rows) > 0:
                message = f"Grant already exists. Grant processing rollback complete"
                return {
                    "status": 0,
                    "exists": 1,
                    "message": message
                }

            grantRequest = WinnForum.GrantRequest(item["secondaryUserID"], None)
            ofr = WinnForum.FrequencyRange(item["minFrequency"], item["maxFrequency"])
            grantRequest.operationParam = WinnForum.OperationParam(item["powerLevel"], ofr)
            vtgp = WinnForum.VTGrantParams(
                None, None, item["preferredFrequency"], item["frequencyAbsolute"],
                item["minBandwidth"], item["preferredBandwidth"], item["preferredBandwidth"],
                item["startTime"], item["endTime"], item["approximateByteSize"],
                item["dataType"], item["powerLevel"], item["location"], item["mobility"],
                item["maxVelocity"]
            )
            grantRequest.vtGrantParams = vtgp

            grantResponse = self.algorithms.runGrantAlgorithm(self.__grantRecords, self.rem, grantRequest)  # algorithm
            grantResponse.grantId = str(uuid.uuid4())

            if grantResponse.response.responseCode == "0":
                g = WinnForum.Grant(
                    grantResponse.grantId, item["cbsdId"], grantResponse.operationParam,
                    vtgp, grantResponse.grantExpireTime
                )
                self.__grantRecords.append(g)

            responseArr.append(grantResponse.asdict())
            insertionArr.append(item)

        try:
            self.CONNECTION.execute(self.GRANTS.insert(), insertionArr)
        except Exception as err:
            print(str(err))
            return {
                "status": 0,
                "message": f"Grant request could not be completed due to '{str(err)}'. Contact an administrator."
            }

        return {
            "status": 1,
            "message": "Grants have been created",
            "grantResponse": responseArr
        }




