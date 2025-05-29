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
import json
import os
import re
import time
from typing import Any, List, Type

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, ConfigDict, Field

import pandas as pd
from sklearn.ensemble import IsolationForest

from lumyn.config.tools import AnomalyDetectionCustomToolPrompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NoInput(BaseModel):
    """Empty input schema for tools that don't require parameters."""
    pass


class AnomalyDetectionCustomTool(BaseTool):
    name: str = "AnomalyDetection Tool"
    description: str = AnomalyDetectionCustomToolPrompt
    cache_function: bool = False
    args_schema: Type[BaseModel] = NoInput

    def fit_model(self, model, data, column):
        df = data.copy()
        data_to_predict = data[column].to_numpy().reshape(-1, 1)
        predictions = model.fit_predict(data_to_predict)
        df['Predictions'] = predictions
        return df

    def _run(self) -> str:
        try:
            df = pd.read_csv('../../../data/intermediate_data.csv')

            iso_forest = IsolationForest(n_estimators=125)
            grouped_sum_hour = df.groupby(['start_date', 'start_time', 'ChargePeriodStart'])[['BilledCost', 'ContractedCost', 'ContractedUnitPrice', 'EffectiveCost', 'ListCost', 'ListUnitPrice', 'period' ]].sum()

            iso_df = self.fit_model(iso_forest, grouped_sum_hour, 'EffectiveCost')
            iso_df['Predictions'] = iso_df['Predictions'].map(lambda x: 1 if x==-1 else 0)
            return iso_df.values.tolist()
        except Exception as exc:
            logger.error(f"AnomalyDetection Tool failed with: {exc}")
            return f"AnomalyDetection Tool failed with: {exc}"
