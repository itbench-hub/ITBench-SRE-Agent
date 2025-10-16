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

from dotenv import load_dotenv

from lumyn.llm_backends.init_backend import get_llm_backend_for_tools
from lumyn.tools.llm_analyzer import LLMAnalyzerCustomTool

# Load environment variables from the .env file
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_TEXT = """
Urbana and Champaign are two adjoining cities in central Illinois that together form the University of Illinois at Urbana-Champaign campus. Their history is intertwined, with each city developing unique characteristics while serving as key locations for education, agriculture, and industry in the region.

### Early History
The land that would become Urbana and Champaign was originally inhabited by various Native American tribes, including the Kickapoo. European settlers arrived in the early 19th century, following the War of 1812 and the signing of various treaties. The fertile soil and potential for agriculture attracted settlers to this part of Illinois.

### Founding and Development
Urbana was established first, in 1833, as the county seat of Champaign County. The town was named after Urbana, Ohio, reflecting the origins of several early settlers. Champaign was founded later, in 1855, originally known as "West Urbana." The establishment of the Illinois Central Railroad was pivotal to its growth, as it connected the area to Chicago in the north and New Orleans in the south, facilitating transport and commerce.

### The University of Illinois
A significant moment in the area's history was the founding of the Illinois Industrial University (now the University of Illinois at Urbana-Champaign) in 1867. This was part of the Morrill Act, which established land-grant colleges across the United States. The university has since become a world-renowned institution, driving much of the economic, cultural, and demographic development of the area.

### Growth and Industry
Throughout the late 19th and early 20th centuries, Urbana and Champaign grew steadily. The arrival of industry, particularly related to agriculture, bolstered the region's economy. Several manufacturing enterprises established themselves in the area, taking advantage of the railroad network and the availability of raw materials.

### Social and Cultural Development
The presence of the university played an instrumental role in shaping the cultural fabric of Urbana-Champaign. The influx of students and faculty brought diversity and vibrancy to the area, with numerous cultural events, theaters, and museums establishing themselves over the decades. The Krannert Center for the Performing Arts and the Spurlock Museum are notable institutions that contribute to the local cultural scene.

### Civil Rights Movement
In the mid-20th century, Urbana-Champaign, like much of the United States, was affected by the Civil Rights Movement. Efforts to promote equality and integration were evident both in the community and on the university campus. These efforts spurred various social and political changes, aligning with the broader national movements for civil and human rights.

### Modern Era
In recent decades, Urbana and Champaign have continued to evolve, driven largely by technology and educational advancements. The university remains a central force, heavily involved in research and innovation, particularly in fields such as engineering, computer science, and agriculture. The local economy has also diversified, with a burgeoning technology sector that includes numerous startups and established tech companies.

In summary, Urbana-Champaign’s history is marked by its foundation as a key agricultural and educational hub in Illinois, evolving into a vibrant community centered around a leading public research university. Its development reflects broader trends within the United States, including industrialization, urbanization, and the ongoing pursuit of innovation and equality.
"""


def test_llm_analyzer():
    # Instantiate the tool
    tool = LLMAnalyzerCustomTool(llm_backend=get_llm_backend_for_tools())

    # Define a natural language query
    nl_query = f"Please generate a short summary of the following text:\n {SAMPLE_TEXT}."

    # Call the tool's _run method to test it
    result = tool._run(nl_query)
    logger.info(f"Result from the tool: \n{result}")
    print(result)


if __name__ == "__main__":
    test_llm_analyzer()
