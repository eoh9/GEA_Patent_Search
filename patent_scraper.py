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
        self.api_key_manager = APIKeyManager()
        self.api_key = self.api_key_manager.get_openai_api_key()
        self.client = OpenAI(api_key=self.api_key)
        self.analysis_agent = EnhancedPatentAnalysisAgent()
        
    def search_patents(self, query: str, num_results: int = Constants.DEFAULT_NUM_RESULTS) -> List[Dict]:
        """Patent search using OpenAI web search - Enhanced version with error handling"""
        try:
            logging.info(f"Starting OpenAI web search for patents: {query}")
            
            # Check API key
            if not self.api_key:
                logging.error("OpenAI API key is not set")
                st.error("OpenAI API key is not configured. Please check your environment variables.")
                return []
            
            # Create web search prompt
            search_prompt = f"""
            Find patent information related to: {query}
            
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
            - description: Brief the core technical description (max 500 words)
            
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
                    model="gpt-4o-search-preview",
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
        """Enhanced method to extract patent information from various GPT response formats"""
        patents = []
        logging.info("Attempting to extract patent information from GPT response")
        
        # Remove code blocks and clean text
        response_text = re.sub(r'```json\s*(.*?)\s*```', r'\1', response_text, flags=re.DOTALL)
        response_text = re.sub(r'```\s*(.*?)\s*```', r'\1', response_text, flags=re.DOTALL)
        
        # Method 1: Try to extract JSON array
        array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', response_text)
        if array_match:
            try:
                array_text = array_match.group(0)
                # Handle possible newline and escape issues
                array_text = array_text.replace('\n', ' ').replace('\\n', '\\\\n')
                patents = json.loads(array_text)
                logging.info(f"Successfully extracted JSON array with {len(patents)} patents")
                return patents
            except json.JSONDecodeError as e:
                logging.error(f"JSON array parse error: {str(e)}")
                # Continue to next method
        
        # Method 2: Try to extract individual patent objects
        object_matches = list(re.finditer(r'\{\s*"title"[\s\S]*?"description"[\s\S]*?\}', response_text))
        if not object_matches:
            # Try multiple format patterns
            object_matches = list(re.finditer(r'\{\s*"title"[\s\S]*?\}', response_text))
        
        if object_matches:
            logging.info(f"Found {len(object_matches)} potential patent objects")
            for match in object_matches:
                try:
                    object_text = match.group(0)
                    # Handle newlines and control characters
                    object_text = object_text.replace('\n', ' ')
                    object_text = re.sub(r'[\x00-\x1F\x7F]', '', object_text)
                    patent = json.loads(object_text)
                    patents.append(patent)
                    logging.info(f"Successfully parsed patent: {patent.get('title', 'Unknown')}")
                except json.JSONDecodeError as e:
                    logging.error(f"Patent object parse error: {str(e)}")
                    # Continue to try other objects
        
        # Method 3: Look for numbered patent entries
        if not patents:
            patent_sections = re.split(r'\n\s*\d+\.\s+', response_text)
            if len(patent_sections) > 1:
                # Remove first section if it's not a patent
                if not re.search(r'(?:title|Title|patent_id|Patent ID):', patent_sections[0]):
                    patent_sections = patent_sections[1:]
                
                for section in patent_sections:
                    patent = {}
                    
                    # Extract required fields
                    title_match = re.search(r'(?:title|Title):\s*"?([^"\n]+)"?', section)
                    if title_match:
                        patent["title"] = title_match.group(1).strip()
                    
                    id_match = re.search(r'(?:patent_id|Patent ID|Patent Number):\s*"?([^",\n]+)"?', section)
                    if id_match:
                        patent["patent_id"] = id_match.group(1).strip()
                    
                    # Extract other fields
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
                    
                    # Extract inventors array
                    inventors_match = re.search(r'(?:inventors|Inventors):\s*\[(.*?)\]', section, re.DOTALL)
                    if inventors_match:
                        inventors_text = inventors_match.group(1)
                        # Extract quoted names
                        inventor_names = re.findall(r'"([^"]+)"', inventors_text)
                        if not inventor_names:
                            # Handle unquoted names
                            inventor_names = [name.strip() for name in inventors_text.split(',')]
                        patent["inventors"] = inventor_names
                    
                    # Extract claims field
                    claims_match = re.search(r'(?:claims|Claims):\s*\[(.*?)\]', section, re.DOTALL)
                    if claims_match:
                        claims_text = claims_match.group(1)
                        # Extract quoted claims
                        claims = re.findall(r'"([^"]+)"', claims_text)
                        if not claims:
                            # Handle unquoted claims
                            claims = [claim.strip() for claim in claims_text.split(',')]
                        patent["claims"] = claims
                    
                    # Extract link
                    link_match = re.search(r'(?:link|Link|URL):\s*"?(http[^",\n]+)"?', section)
                    if link_match:
                        patent["link"] = link_match.group(1).strip()
                    
                    # Add only if required fields are present
                    if "title" in patent and "patent_id" in patent:
                        patents.append(patent)
        
        # Method 4: Direct patent field matching
        if not patents:
            # Find title/ID pairs
            title_matches = list(re.finditer(r'(?:title|Title):\s*"?([^"\n]+)"?', response_text))
            id_matches = list(re.finditer(r'(?:patent_id|Patent ID|Patent Number):\s*"?([^",\n]+)"?', response_text))
            
            if len(title_matches) > 0 and len(title_matches) == len(id_matches):
                logging.info(f"Found {len(title_matches)} title/ID pairs, attempting direct extraction")
                
                for i in range(len(title_matches)):
                    patent = {
                        "title": title_matches[i].group(1).strip(),
                        "patent_id": id_matches[i].group(1).strip()
                    }
                    
                    # Extract text between title and ID to find other fields
                    start_pos = title_matches[i].start()
                    end_pos = id_matches[i].end() if i == len(title_matches) - 1 else title_matches[i + 1].start()
                    section = response_text[start_pos:end_pos]
                    
                    # Extract other fields like abstract, date, assignee, etc.
                    abstract_match = re.search(r'(?:abstract|Abstract):\s*"?([^"]+?)"?(?=\n\w+:|$)', section, re.DOTALL)
                    if abstract_match:
                        patent["abstract"] = abstract_match.group(1).strip()
                    
                    # Add only if required fields are present
                    patents.append(patent)
        
        # Return results
        if patents:
            logging.info(f"Successfully extracted {len(patents)} patents")
            return patents
        
        logging.warning("Failed to extract patent information from response")
        return []
    
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
    
    def close(self):
        """Clean up resources"""
        pass  # No cleanup needed when using OpenAI API
