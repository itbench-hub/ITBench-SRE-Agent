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


import json
import time
from typing import Dict, List, Optional

from pydantic import BaseModel, ValidationError


class ArgumentsModel(BaseModel):
    service: str
    start_time: int
    end_time: int
    limit: int
    error_traces_only: Optional[bool] = False
    operation: Optional[str] = None


class JaegerLinter:
    def __init__(self):
        pass

    def lint(self, arguments, services, operations, current_time: int):
        max_time = 43200000000
        lower_limit = 1
        upper_limit = 5
        # alert_generation_time: int = int(time.time_ns() / 1000),
        # threshold_for_golden_period: int = 1800000) -> str:

        try:
            args = ArgumentsModel.model_validate_json(json.dumps(arguments))
            lint_message = str()

            if args.start_time == args.end_time:
                lint_message += "Invalid start time. start time and end time cannot be the same."
            if args.end_time - args.start_time > max_time:
                lint_message += f"Invalid start time. start time should be within {max_time} of end time."
            if not (lower_limit <= args.limit <= upper_limit):
                lint_message += f"Invalid limit. Limit should be between {lower_limit} and {upper_limit}."
            if args.service not in services:
                lint_message += f"{args.service} is an Invalid service name, Valid service names are {services}."
            if args.operation not in operations and args.operation is not None:
                lint_message += f"Invalid operation, Valid operations are {operations} or None to use all operations."
            # if not (alert_generation_time - threshold_for_golden_period <= args.end_time <= current_time):
            #   lint_message += f"Invalid end time. End time should be between {alert_generation_time - threshold_for_golden_period} and {current_time}."

            if lint_message:
                return lint_message
            else:
                return arguments

        except ValidationError as e:
            return f"Argument validation error: {e}"
        except ValueError as e:
            return f"Invalid Jaeger Query: {e}"
        except Exception as e:
            return f"An error occurred: {e}"
