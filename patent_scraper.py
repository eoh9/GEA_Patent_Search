import os
import logging
from dotenv import load_dotenv
import json
import re
import traceback
from typing import List, Dict, Optional
from openai import OpenAI
from patent import EnhancedPatentAnalysisAgent
import streamlit as st
from api_key_manager import APIKeyManager

class Constants:
    DEFAULT_NUM_RESULTS = 20

class PatentScraper:
    """Patent search and analysis system"""
    
    def __init__(self):
        """Initialize the scraper with API key"""
        self.api_key = APIKeyManager.get_openai_api_key()
        self.client = OpenAI(api_key=self.api_key)
        self.analysis_agent = EnhancedPatentAnalysisAgent()
        
    def search_patents(self, query: str, num_results: int = Constants.DEFAULT_NUM_RESULTS) -> List[Dict]:
        """Patent search using OpenAI web search - Enhanced version with error handling"""
        try:
            logging.info(f"Starting OpenAI web search for patents: {query}")
            
            # API 키 확인
            if not self.api_key:
                logging.error("OpenAI API key is not set")
                st.error("OpenAI API key is not configured. Please check your environment variables.")
                return []
            
            # Create web search prompt
            search_prompt = f"""
            I need patent information related to: {query}
            
            Return the information as a JSON array. The response must begin with '[' and end with ']'.
            Do not include any text before or after the JSON array.
            
            Each patent object in the array must have these fields:
            - title: Patent Title
            - patent_id: Patent ID/Number
            - publication_date: Publication Date
            - inventors: List of inventors
            - assignee: Assignee Name
            - abstract: Full abstract text
            - claims: List of top 3-5 claims
            - cpc_classifications: CPC Classifications
            - link: Patent URL (IMPORTANT: use Google Patents URL format: https://patents.google.com/patent/PATENT_ID)
            - description: Brief technical description (max 200 words)
            
            Limit to {num_results} patents maximum.
            
            IMPORTANT:
            1. Ensure all strings are properly escaped
            2. Your response must be ONLY the JSON array
            3. Do not include ```json or ``` markdown code blocks
            4. For patent links, ALWAYS use Google Patents format: https://patents.google.com/patent/PATENT_ID
            """
            
            # Enhanced system message
            system_message = """
            You are a patent search API that returns ONLY valid JSON arrays.
            Do not include ANY explanatory text, comments, or code block formatting.
            Begin your response with [ and end with ] - the entire response must be a valid JSON array.
            Properly escape all strings, especially those containing quotes.
            ALWAYS format patent links as Google Patents URLs: https://patents.google.com/patent/PATENT_ID
            """
            
            try:
                # Execute OpenAI web search
                response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": search_prompt}
                    ],
                    max_tokens=4000
                )
                
                # Get response content
                response_content = response.choices[0].message.content
                
                # Log sample for debugging
                sample_length = min(500, len(response_content))
                logging.debug(f"Response sample (first {sample_length} chars): {response_content[:sample_length]}...")
                
                # Enhanced parsing attempt
                patents = self._parse_gpt_response(response_content)
                
                if not patents:
                    logging.warning("No patents found in the search results.")
                    st.warning("No patents found for your search query. Please try different keywords.")
                    return []
                
                # Process patent data
                processed_patents = self._process_patent_data(patents)
                
                # Add analysis results
                processed_patents_with_analysis = []
                for patent in processed_patents:
                    try:
                        analysis_result = self.analysis_agent.analyze_patent_similarity(query, patent)
                        patent.update(analysis_result)
                        processed_patents_with_analysis.append(patent)
                    except Exception as e:
                        logging.error(f"Error analyzing patent similarity: {str(e)}")
                        # Include patent even if analysis fails
                        patent['relevance_score'] = 0.0  # Default score
                        patent['similarity_explanation'] = "Similarity analysis failed."
                        processed_patents_with_analysis.append(patent)
                
                # Sort by relevance score
                processed_patents_with_analysis.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
                
                logging.info(f"Successfully processed {len(processed_patents_with_analysis)} patents")
                return processed_patents_with_analysis
                
            except Exception as e:
                logging.error(f"OpenAI API call failed: {str(e)}")
                st.error(f"Failed to search patents: {str(e)}")
                return []
            
        except Exception as e:
            logging.error(f"Search error: {str(e)}")
            traceback.print_exc()
            st.error(f"An unexpected error occurred: {str(e)}")
            return []
    
    def _parse_gpt_response(self, response_text: str) -> List[Dict]:
        """다양한 형식의 GPT 응답에서 특허 정보를 추출하는 강화된 메서드"""
        patents = []
        logging.info("Attempting to extract patent information from GPT response")
        
        # 코드 블록 제거 및 텍스트 정리
        response_text = re.sub(r'```json\s*(.*?)\s*```', r'\1', response_text, flags=re.DOTALL)
        response_text = re.sub(r'```\s*(.*?)\s*```', r'\1', response_text, flags=re.DOTALL)
        
        # 방법 1: JSON 배열 추출 시도
        array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', response_text)
        if array_match:
            try:
                array_text = array_match.group(0)
                # 가능한 개행 문자와 이스케이프 문제 해결
                array_text = array_text.replace('\n', ' ').replace('\\n', '\\\\n')
                patents = json.loads(array_text)
                logging.info(f"Successfully extracted JSON array with {len(patents)} patents")
                return patents
            except json.JSONDecodeError as e:
                logging.error(f"JSON array parse error: {str(e)}")
                # 다음 방법으로 진행
        
        # 방법 2: 개별 특허 객체 추출 시도
        object_matches = list(re.finditer(r'\{\s*"title"[\s\S]*?"description"[\s\S]*?\}', response_text))
        if not object_matches:
            # 여러 형식 패턴 시도
            object_matches = list(re.finditer(r'\{\s*"title"[\s\S]*?\}', response_text))
        
        if object_matches:
            logging.info(f"Found {len(object_matches)} potential patent objects")
            for match in object_matches:
                try:
                    object_text = match.group(0)
                    # 줄바꿈 및 제어 문자 처리
                    object_text = object_text.replace('\n', ' ')
                    object_text = re.sub(r'[\x00-\x1F\x7F]', '', object_text)
                    patent = json.loads(object_text)
                    patents.append(patent)
                    logging.info(f"Successfully parsed patent: {patent.get('title', 'Unknown')}")
                except json.JSONDecodeError as e:
                    logging.error(f"Patent object parse error: {str(e)}")
                    # 계속 진행하여 다른 객체 시도
        
        # 방법 3: 번호가 매겨진 특허 항목 찾기
        if not patents:
            patent_sections = re.split(r'\n\s*\d+\.\s+', response_text)
            if len(patent_sections) > 1:
                # 첫 번째 섹션이 특허가 아닌 경우 제거
                if not re.search(r'(?:title|Title|patent_id|Patent ID):', patent_sections[0]):
                    patent_sections = patent_sections[1:]
                
                for section in patent_sections:
                    patent = {}
                    
                    # 필수 필드 추출
                    title_match = re.search(r'(?:title|Title):\s*"?([^"\n]+)"?', section)
                    if title_match:
                        patent["title"] = title_match.group(1).strip()
                    
                    id_match = re.search(r'(?:patent_id|Patent ID|Patent Number):\s*"?([^",\n]+)"?', section)
                    if id_match:
                        patent["patent_id"] = id_match.group(1).strip()
                    
                    # 다른 필드들도 추출
                    abstract_match = re.search(r'(?:abstract|Abstract):\s*"?([^"]+?)"?(?=\n\w+:|$)', section, re.DOTALL)
                    if abstract_match:
                        patent["abstract"] = abstract_match.group(1).strip()
                    
                    date_match = re.search(r'(?:publication_date|Publication Date):\s*"?([^",\n]+)"?', section)
                    if date_match:
                        patent["publication_date"] = date_match.group(1).strip()
                    
                    assignee_match = re.search(r'(?:assignee|Assignee):\s*"?([^",\n]+)"?', section)
                    if assignee_match:
                        patent["assignee"] = assignee_match.group(1).strip()
                    
                    desc_match = re.search(r'(?:description|Description):\s*"?([^"]+?)"?(?=\n\w+:|$)', section, re.DOTALL)
                    if desc_match:
                        patent["description"] = desc_match.group(1).strip()
                    
                    # 발명자 배열 추출
                    inventors_match = re.search(r'(?:inventors|Inventors):\s*\[(.*?)\]', section, re.DOTALL)
                    if inventors_match:
                        inventors_text = inventors_match.group(1)
                        # 따옴표로 묶인 이름 추출
                        inventor_names = re.findall(r'"([^"]+)"', inventors_text)
                        if not inventor_names:
                            # 따옴표가 없는 경우
                            inventor_names = [name.strip() for name in inventors_text.split(',')]
                        patent["inventors"] = inventor_names
                    
                    # claims 필드 형식 확인 및 추출
                    claims_match = re.search(r'(?:claims|Claims):\s*\[(.*?)\]', section, re.DOTALL)
                    if claims_match:
                        claims_text = claims_match.group(1)
                        # 따옴표로 묶인 클레임 추출
                        claims = re.findall(r'"([^"]+)"', claims_text)
                        if not claims:
                            # 따옴표가 없는 경우
                            claims = [claim.strip() for claim in claims_text.split(',')]
                        patent["claims"] = claims
                    
                    # 연결 링크 추출
                    link_match = re.search(r'(?:link|Link|URL):\s*"?(http[^",\n]+)"?', section)
                    if link_match:
                        patent["link"] = link_match.group(1).strip()
                    
                    # 필수 필드가 있는 경우에만 추가
                    if "title" in patent and "patent_id" in patent:
                        patents.append(patent)
        
        # 방법 4: 직접 특허 필드 매칭
        if not patents:
            # 제목/ID 쌍 찾기
            title_matches = list(re.finditer(r'(?:title|Title):\s*"?([^"\n]+)"?', response_text))
            id_matches = list(re.finditer(r'(?:patent_id|Patent ID|Patent Number):\s*"?([^",\n]+)"?', response_text))
            
            if len(title_matches) > 0 and len(title_matches) == len(id_matches):
                logging.info(f"Found {len(title_matches)} title/ID pairs, attempting direct extraction")
                
                for i in range(len(title_matches)):
                    patent = {
                        "title": title_matches[i].group(1).strip(),
                        "patent_id": id_matches[i].group(1).strip()
                    }
                    
                    # 제목과 ID 사이의 텍스트 추출하여 다른 필드 찾기
                    start_pos = title_matches[i].start()
                    end_pos = id_matches[i].end() if i == len(title_matches) - 1 else title_matches[i + 1].start()
                    section = response_text[start_pos:end_pos]
                    
                    # abstract, date, assignee 등과 같은 다른 필드들도 추출
                    abstract_match = re.search(r'(?:abstract|Abstract):\s*"?([^"]+?)"?(?=\n\w+:|$)', section, re.DOTALL)
                    if abstract_match:
                        patent["abstract"] = abstract_match.group(1).strip()
                    
                    # 필수 필드가 있는 경우에만 추가
                    patents.append(patent)
        
        # 결과 반환
        if patents:
            logging.info(f"Successfully extracted {len(patents)} patents")
            return patents
        
        logging.warning("Failed to extract patent information from response")
        return []
    
    def _extract_patents_from_text(self, text: str) -> List[Dict]:
        """Try to extract patent information from unstructured text"""
        patents = []
        
        try:
            # Find patent information blocks
            patent_blocks = re.split(r'\n\s*\n', text)
            
            for block in patent_blocks:
                patent = {}
                
                # Extract title
                title_match = re.search(r'(?:title|Title):\s*"?([^"\n]+)"?', block)
                if title_match:
                    patent["title"] = title_match.group(1).strip()
                    
                # Extract patent ID
                id_match = re.search(r'(?:patent_id|Patent ID|Patent Number):\s*"?([^",\n]+)"?', block)
                if id_match:
                    patent["patent_id"] = id_match.group(1).strip()
                    
                # Extract abstract
                abstract_match = re.search(r'(?:abstract|Abstract):\s*"?([^"]+?)(?:"|(?=\n\w+:))', block, re.DOTALL)
                if abstract_match:
                    patent["abstract"] = abstract_match.group(1).strip()
                    
                # Extract inventors
                inventors_match = re.search(r'(?:inventors|Inventors):\s*\[(.*?)\]', block)
                if inventors_match:
                    inventors = re.findall(r'"([^"]+)"', inventors_match.group(1))
                    patent["inventors"] = [inv.strip() for inv in inventors]
                
                # Extract assignee
                assignee_match = re.search(r'(?:assignee|Assignee):\s*"?([^"\n]+)"?', block)
                if assignee_match:
                    patent["assignee"] = assignee_match.group(1).strip()
                
                # Extract publication date
                date_match = re.search(r'(?:publication_date|Publication Date):\s*"?([^"\n]+)"?', block)
                if date_match:
                    patent["publication_date"] = date_match.group(1).strip()
                    
                # Extract CPC classifications
                cpc_match = re.search(r'(?:cpc_classifications|CPC Classifications):\s*\[(.*?)\]', block)
                if cpc_match:
                    cpcs = re.findall(r'"([^"]+)"', cpc_match.group(1))
                    patent["cpc_classifications"] = [cpc.strip() for cpc in cpcs]
                
                # Extract claims
                claims_match = re.search(r'(?:claims|Claims):\s*\[(.*?)\]', block, re.DOTALL)
                if claims_match:
                    claims = re.findall(r'"([^"]+)"', claims_match.group(1))
                    patent["claims"] = [claim.strip() for claim in claims]
                
                # Extract link
                link_match = re.search(r'(?:link|Link|URL):\s*"?([^"\n]+)"?', block)
                if link_match:
                    patent["link"] = link_match.group(1).strip()
                    
                # Extract description
                desc_match = re.search(r'(?:description|Description):\s*"?([^"]+?)(?:"|(?=\n\w+:))', block, re.DOTALL)
                if desc_match:
                    patent["description"] = desc_match.group(1).strip()
                
                # Add only if minimum required fields are present
                if patent.get("title") and patent.get("patent_id"):
                    patents.append(patent)
                    logging.info(f"Extracted patent: {patent['title']}")
            
        except Exception as e:
            logging.error(f"Error extracting patents from text: {str(e)}")
        
        return patents
    
    def _process_patent_data(self, patents: List[Dict]) -> List[Dict]:
        """Process patent data into standardized format with enhanced Google Patent links"""
        processed_patents = []
        
        if not isinstance(patents, list):
            logging.error(f"Expected list of patents, got {type(patents)}")
            return []
        
        for patent in patents:
            try:
                # Check if abstract or description is available
                abstract = patent.get("abstract", "")
                description = patent.get("description", "")
                
                # If both are available, prefer abstract for the description field
                content_text = abstract if abstract else description
                
                # Format patent ID
                patent_id = str(patent.get("patent_id", ""))
                
                # Format Google Patent link
                link = patent.get("link", "")
                if not link or not link.startswith("http"):
                    link = f"https://patents.google.com/patent/{patent_id}" if patent_id else ""
                
                processed_patent = {
                    "title": str(patent.get("title", "")),
                    "patent_id": patent_id,
                    "abstract": str(abstract),
                    "description": str(content_text),
                    "link": link,
                    "inventors": patent.get("inventors", []),
                    "assignee": str(patent.get("assignee", "")),
                    "publication_date": str(patent.get("publication_date", "")),
                    "cpc_classifications": patent.get("cpc_classifications", []),
                    "claims": patent.get("claims", [])
                }
                
                processed_patents.append(processed_patent)
                logging.info(f"Patent {len(processed_patents)} processed successfully")
                
            except Exception as e:
                logging.error(f"Error processing patent: {str(e)}")
                continue
        
        return processed_patents
    
    def _calculate_similarity_explanation(self, idea_description, patent_data):
        """Generate a detailed explanation of why a patent is similar to the user's idea"""
        try:
            # Extract the key information from the patent
            patent_title = patent_data.get('title', '')
            patent_abstract = patent_data.get('abstract', '')
            patent_description = patent_data.get('description', '')
            
            # Create a prompt for the explanation
            prompt = f"""
            Compare this user's patent idea with an existing patent and explain in detail WHY they are similar or different.
            
            USER'S IDEA:
            {idea_description}
            
            EXISTING PATENT:
            Title: {patent_title}
            Abstract: {patent_abstract}
            Description: {patent_description}
            
            Provide a detailed technical explanation (200+ words) covering:
            1. Core technological similarities and differences
            2. Implementation approaches comparison
            3. Potential overlapping claims
            4. Unique aspects of each
            5. How the existing patent might impact the patentability of the user's idea
            
            Format the response as a detailed technical analysis focused on helping the user understand the relevance of this patent to their invention.
            """
            
            # Get explanation from OpenAI
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1000
            )
            
            explanation = response.choices[0].message.content
            return explanation
            
        except Exception as e:
            logging.error(f"Error generating similarity explanation: {str(e)}")
            return "Could not generate detailed similarity explanation due to an error."
    
    def close(self):
        """Clean up resources"""
        pass  # No cleanup needed when using OpenAI API
