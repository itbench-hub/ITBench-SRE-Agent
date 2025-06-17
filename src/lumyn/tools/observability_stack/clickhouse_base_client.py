# Copyright contributors to the ITBench project. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
import os
from typing import Any, List, Optional
import mysql.connector

import csv

import clickhouse_connect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 120))
RETRY_TOTAL = int(os.getenv("RETRY_TOTAL", 3))


class ClickHouseBaseClient:
    clickhouse_url: Optional[str] = None
    clickhouse_port: Optional[str] = None
    clickhouse_username: Optional[str] = None
    clickhouse_password: Optional[str] = None
    client: Optional[Any] = None
    cursor: Optional[Any] = None
    connection: Optional[Any] = None

    def model_post_init(self):
        self.clickhouse_url = os.environ.get("OBSERVABILITY_STACK_URL")
        self.clickhouse_port = os.environ.get("OBSERVABILITY_STACK_PORT")
        self.clickhouse_username = os.environ.get("CLICKHOUSE_USERNAME")
        self.clickhouse_password = os.environ.get("CLICKHOUSE_PASSWORD")

        if self.clickhouse_url is None or self.clickhouse_username is None or self.clickhouse_password is None:
            raise ValueError(
                "Observability Stack URL-ClickHouse URL, username and password must be provided through environment variables"
            )

        # self.client = clickhouse_connect.get_client(host=self.clickhouse_url,
        #                                             port=self.clickhouse_port,
        #                                             proxy_path="clickhouse",
        #                                             username=self.clickhouse_username,
        #                                             password=self.clickhouse_password,
        #                                             query_retries=RETRY_TOTAL,
        #                                             connect_timeout=REQUEST_TIMEOUT)
        db_config = {
               'host': os.environ.get("MYSQL_HOST"),
                'user': os.environ.get("MYSQL_USER"),  # Replace with your MySQL username
                'password': os.environ.get("MYSQL_PASS"),  # Replace with your MySQL password
                'database': os.environ.get("MYSQL_DB")  # Replace with your database name
        }
        self.connection = mysql.connector.connect(**db_config)
        self.cursor = self.connection.cursor()



    def _query(self, query: str) -> List:
        try:
            # result = self.client.query(query)
            print("****************Executing query *************")
            self.cursor.execute(query)
            
            result = self.cursor.fetchall()
            # columns = [desc[0] for desc in self.cursor.description]  # Column headers

            # Write results to a CSV file locally
            # with open('intermediate_data.csv', mode='w', newline='', encoding='utf-8') as file:
            #     writer = csv.writer(file)
            #     writer.writerow(columns)  # Write headers
            #     writer.writerows(result)    # Write data rows



            # print("+++++++++++++++++++++++++++++++++")
            # print("result: ",result)
            # print("+++++++++++++++++++++++++++++++")
            return result
            # return "File saved!!"
            # return result.result_rows
            # print("cursor output: ", self.cursor.fetchall())
            # return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Request to ClickHouse failed: {e}")
            raise
