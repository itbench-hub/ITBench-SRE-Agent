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


import sqlfluff


class SQLLinter:
    def __init__(self):
        pass

    @staticmethod
    def lint(query: str, dialect="clickhouse") -> str:
        violations = sqlfluff.lint(query, dialect=dialect, exclude_rules=["LT12","LT05", "LT09", "LT01", "CP02"])
        if violations:
            # print("********************************violation")
            return f"Invalid {dialect} SQL Query: {violations}"
        # print("*******************Query after linter:", query)
        return query
