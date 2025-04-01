import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io
import os
import requests
import json
import logging
import traceback
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
import concurrent.futures
from dotenv import load_dotenv
import tempfile
import uuid
import numpy as np
from io import BytesIO
from PIL import Image
from openai import OpenAI
from patent_scraper import PatentScraper

# Ensure all required modules are imported
try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    import graphviz
except ImportError:
    st.error("Required libraries are not installed. Please install them using: pip install python-pptx graphviz")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load environment variables
load_dotenv()

# Import local modules
from patent_scraper import PatentScraper
from patent import EnhancedPPTGenerator, EnhancedPatentAnalysisAgent

# Constants class
class Constants:
    GPT_MODEL = "gpt-3.5-turbo"
    GPT_MODEL_4 = "gpt-4"
    DEFAULT_ERROR_MESSAGE = "Analysis Failed"
    DEFAULT_IMAGE_SIZE = "1024x1024"
    DEFAULT_IMAGE_QUALITY = "standard"
    DEFAULT_NUM_IMAGES = 1
    DEFAULT_SIMILARITY_THRESHOLD = 3.0
    DEFAULT_NUM_RESULTS = 20
    DEFAULT_TOP_N = 5

def setup_page():
    """Set up the Streamlit page configuration"""
    st.set_page_config(
        page_title="Patent Search & Analysis",
        page_icon="🔍",
        layout="wide"
    )
    
    st.title("Patent Search & Analysis System")

def visualize_patent_similarities(patents, idea_description):
    """Create visualizations to show similarities between patents and the user's idea"""
    if not patents or len(patents) == 0:
        return None
        
    # Filter patents that have relevance scores
    analyzed_patents = [p for p in patents if 'relevance_score' in p]
    if not analyzed_patents:
        st.warning("No relevance scores available for visualization.")
        return None
        
    # Sort patents by relevance score
    sorted_patents = sorted(analyzed_patents, key=lambda x: x.get('relevance_score', 0), reverse=True)[:5]  # Top 5 patents
    
    # Create figures
    figures = []
    
    # 1. Bar chart for similarity comparison
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    
    # Prepare data for bar chart
    titles = [p.get('title', f"Patent {i}")[:50] + "..." for i, p in enumerate(sorted_patents)]
    scores = [p.get('relevance_score', 0) for p in sorted_patents]
    
    # Create horizontal bar chart with custom colors
    colors = ['#2ecc71' if score >= 75 else '#f1c40f' if score >= 50 else '#e74c3c' for score in scores]
    bars = ax1.barh(titles, scores, color=colors)
    
    # Customize chart
    ax1.set_xlabel('Relevance Score (%)')
    ax1.set_title('Patent Similarity Comparison')
    ax1.set_xlim(0, 100)
    
    # Add value labels
    for i, v in enumerate(scores):
        ax1.text(v + 1, i, f'{v:.1f}%', va='center')
    
    # Save to a BytesIO object
    buf1 = io.BytesIO()
    fig1.tight_layout()
    fig1.savefig(buf1, format='png', dpi=300, bbox_inches='tight')
    buf1.seek(0)
    figures.append(buf1)
    
    # 2. Radar chart for semantic analysis (if available)
    semantic_scores = [p.get('semantic_score', 0) for p in sorted_patents]
    keyword_scores = [p.get('keyword_score', 0) for p in sorted_patents]
    
    if any(semantic_scores) and any(keyword_scores):
        fig2, ax2 = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
        
        # Prepare data for radar chart
        categories = ['Semantic\nSimilarity', 'Keyword\nMatch', 'Overall\nRelevance']
        num_vars = len(categories)
        
        # Calculate angles for radar chart
        angles = [n / float(num_vars) * 2 * np.pi for n in range(num_vars)]
        angles += angles[:1]
        
        # Plot data for each patent
        ax2.set_theta_offset(np.pi / 2)
        ax2.set_theta_direction(-1)
        ax2.set_rlabel_position(0)
        
        # Plot lines
        for i, patent in enumerate(sorted_patents[:3]):  # Top 3 patents only
            values = [
                patent.get('semantic_score', 0),
                patent.get('keyword_score', 0),
                patent.get('relevance_score', 0) / 100
            ]
            values += values[:1]
            
            ax2.plot(angles, values, linewidth=1, linestyle='solid', label=f"Patent {i+1}")
            ax2.fill(angles, values, alpha=0.1)
        
        # Set chart properties
        ax2.set_xticks(angles[:-1])
        ax2.set_xticklabels(categories)
        ax2.set_ylim(0, 1)
        plt.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
        
        # Save radar chart
        buf2 = io.BytesIO()
        fig2.tight_layout()
        fig2.savefig(buf2, format='png', dpi=300, bbox_inches='tight')
        buf2.seek(0)
        figures.append(buf2)
    
    return figures

def display_patent_details(patent):
    """Display detailed information about a patent without nested expanders"""
    st.write(f"**Patent ID:** {patent.get('patent_id', 'N/A')}")
    st.write(f"**Assignee:** {patent.get('assignee', 'N/A')}")
    st.write(f"**Publication Date:** {patent.get('publication_date', 'N/A')}")
    st.write(f"**Inventors:** {', '.join(patent.get('inventors', ['N/A']))}")
    
    # Abstract
    st.write("**Abstract:**")
    if patent.get('abstract'):
        st.write(patent['abstract'])
    else:
        st.write("No abstract available.")
    
    # Technical description
    st.write("**Technical Description:**")
    if patent.get('description'):
        st.write(patent['description'])
    else:
        st.write("No technical description available.")
    
    # Similarity explanation
    if patent.get('similarity_explanation'):
        st.write("**Similarity Analysis:**")
        st.write(patent['similarity_explanation'])
    
    # CPC classifications
    if patent.get('cpc_classifications'):
        st.write("**CPC Classifications:**")
        for cpc in patent['cpc_classifications']:
            st.write(f"- {cpc}")
    
    # Claims - Display as plain text without nested expander
    if patent.get('claims'):
        st.write("**Patent Claims:**")
        for i, claim in enumerate(patent['claims'], 1):
            st.write(f"Claim {i}: {claim}")
    
    # Patent link - Fix to ensure proper Google Patent link format
    if patent.get('link'):
        # Check if it's already a Google patent link
        link = patent['link']
        if not link.startswith('http'):
            link = f"https://patents.google.com/patent/{patent.get('patent_id', 'US')}"
        st.write(f"**Patent Link:** [{link}]({link})")
    else:
        # Create Google patent link from patent ID if link is missing
        patent_id = patent.get('patent_id', '')
        if patent_id:
            google_link = f"https://patents.google.com/patent/{patent_id}"
            st.write(f"**Patent Link:** [{google_link}]({google_link})")

def display_similarity_visualizations(idea_description, patents):
    """Display visualizations showing patent similarities"""
    if not patents or len(patents) == 0:
        st.info("No patents available for visualization.")
        return
        
    st.subheader("Patent Similarity Visualization")
    
    # Generate visualizations
    visualizations = visualize_patent_similarities(patents, idea_description)
    
    if visualizations and len(visualizations) > 0:
        # Display the visualizations
        cols = st.columns(len(visualizations))
        for i, viz in enumerate(visualizations):
            with cols[i]:
                st.image(viz, use_column_width=True)
        
        # Add explanation for the visualizations
        st.markdown("""
        **Visualization Interpretation:**
        
        **Left Chart**: Shows relevance scores of top patents. Higher scores indicate greater similarity to your idea.
        - Green (75%+): Very High Relevance
        - Yellow (50-75%): Moderate Relevance
        - Red (<50%): Low Relevance
        
        **Right Chart**: Detailed analysis of top 3 patents:
        - Semantic Similarity: Overall conceptual similarity of the patent
        - Keyword Match: Alignment of key technical terms
        - Overall Relevance: Combined similarity score
        """)
    else:
        st.info("Unable to generate visualizations. Insufficient data available.")

def add_comparison_feature_to_search_results(search_results, idea_description, api_key):
    """Add comparison feature to patent search results display"""
    if not search_results or len(search_results) == 0:
        st.info("No patents available for comparison.")
        return
    
    st.subheader("Compare Your Idea with Patents")
    
    # Allow user to select a patent for comparison
    patent_options = {f"{p.get('title', 'No Title')} (ID: {p.get('patent_id', 'N/A')})": p for p in search_results}
    selected_patent_title = st.selectbox(
        "Select a patent to compare with your idea:",
        options=list(patent_options.keys())
    )
    
    if selected_patent_title:
        selected_patent = patent_options[selected_patent_title]
        
        # Display selected patent info
        st.write(f"**Comparing with:** {selected_patent.get('title', 'N/A')}")
        
        # Create columns for comparison
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Your Idea")
            st.write(idea_description)
        
        with col2:
            st.markdown("### Selected Patent")
            st.write(selected_patent.get('abstract', 'No abstract available'))
        
        # Display similarity analysis
        st.markdown("### Similarity Analysis")
        if selected_patent.get('similarity_explanation'):
            st.write(selected_patent['similarity_explanation'])
        else:
            # Generate new similarity analysis
            analysis_agent = EnhancedPatentAnalysisAgent()
            similarity_explanation = analysis_agent._calculate_similarity_explanation(
                idea_description,
                selected_patent
            )
            st.write(similarity_explanation)
        
        # Add action buttons
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("Generate Differentiation Strategy"):
                with st.spinner("Generating strategy..."):
                    analysis_agent = EnhancedPatentAnalysisAgent()
                    strategy = analysis_agent.recommend_differentiation(
                        idea_description,
                        [selected_patent]
                    )
                    st.markdown("### Differentiation Strategy")
                    st.write(strategy)
        
        with col2:
            if st.button("Analyze Technical Overlap"):
                with st.spinner("Analyzing overlap..."):
                    analysis_agent = EnhancedPatentAnalysisAgent()
                    overlap = analysis_agent._deep_semantic_comparison(
                        idea_description,
                        selected_patent.get('title', ''),
                        selected_patent.get('description', '')
                    )
                    st.markdown("### Technical Overlap Analysis")
                    st.write(overlap)
        
        with col3:
            if st.button("Suggest Improvements"):
                with st.spinner("Generating suggestions..."):
                    analysis_agent = EnhancedPatentAnalysisAgent()
                    suggestions = analysis_agent._generate_improvement_suggestions(idea_description)
                    st.markdown("### Improvement Suggestions")
                    for suggestion in suggestions:
                        st.write(f"- {suggestion}")

def display_search_results(search_query, search_results):
    """Display search results with top 5 patents highlighted"""
    st.success(f"Found {len(search_results)} patents.")
    
    # Display similarity visualizations
    display_similarity_visualizations(search_query, search_results)
    
    # Create a dataframe of all patents
    df = pd.DataFrame(search_results)
    display_cols = ['patent_id', 'title', 'assignee', 'publication_date', 'relevance_score']
    if all(col in df.columns for col in display_cols):
        # Sort by relevance score if available
        if 'relevance_score' in df.columns:
            df = df.sort_values(by='relevance_score', ascending=False)
        
        # Format relevance score as percentage with 1 decimal place if available
        if 'relevance_score' in df.columns:
            df['relevance_score'] = df['relevance_score'].apply(lambda x: f"{x:.1f}%" if pd.notnull(x) else "N/A")
            display_cols_with_score = display_cols
        else:
            display_cols_with_score = display_cols[:-1]  # Remove relevance_score if not available
            
        # Display all patents in a dataframe
        st.dataframe(df[display_cols_with_score], use_container_width=True)
    
    # Display top 5 patents prominently
    st.subheader("Top 5 Most Relevant Patents")
    top_patents = sorted(search_results, key=lambda x: x.get('relevance_score', 0), reverse=True)[:5]
    
    # Show the top 5 patents with expanders
    for idx, patent in enumerate(top_patents, 1):
        relevance = patent.get('relevance_score', 0)
        relevance_text = f" - Relevance: {relevance:.1f}%" if relevance > 0 else ""
        with st.expander(f"{idx}. {patent.get('title', 'No Title')}{relevance_text}"):
            display_patent_details(patent)
    
    # Also show all patents (if more than 5)
    if len(search_results) > 5:
        st.subheader("All Patents")
        for idx, patent in enumerate(search_results, 1):
            if idx > 5:  # Skip the first 5 already shown
                relevance = patent.get('relevance_score', 0)
                relevance_text = f" - Relevance: {relevance:.1f}%" if relevance > 0 else ""
                with st.expander(f"{idx}. {patent.get('title', 'No Title')}{relevance_text}"):
                    display_patent_details(patent)

def update_patent_search_tab():
    """Code for the updated patent search tab"""
    st.header("Patent Search")
    st.write("Search and analyze existing patents.")
    
    # Search form
    with st.form("patent_search_form"):
        search_query = st.text_area("Enter Search Query", 
                               placeholder="Enter the patent content you want to search for")
        num_results = st.slider("Number of Patents to Search", 
                           min_value=5, max_value=50, value=15, 
                           help="Select how many patents to retrieve in total")
        submitted = st.form_submit_button("Search")
    
    # Search execution
    if submitted and search_query:
        with st.spinner("Searching patents..."):
            try:
                # Initialize patent scraper
                scraper = PatentScraper()
                
                # Search patents
                search_results = scraper.search_patents(search_query, num_results=num_results)
                
                # Store results in session state
                st.session_state.search_results = search_results
                st.session_state.idea_description = search_query
                
                # Display results
                if search_results:
                    display_search_results(search_query, search_results)
                else:
                    st.warning("No search results found.")
            except Exception as e:
                st.error(f"Error occurred during patent search: {str(e)}")
                logging.error(f"Patent search error: {str(e)}")
                traceback.print_exc()

def main():
    """Main application function"""
    setup_page()
    
    # Set OpenAI API key configuration
    api_key = os.getenv('OPENAI_API_KEY')
    with st.sidebar:
        st.header("Settings")
        api_key_input = st.text_input("OpenAI API Key", type="password", value=api_key if api_key else "")
        
        if api_key_input:
            os.environ['OPENAI_API_KEY'] = api_key_input
    
    # Create tabs for different functionalities
    tab1, tab2, tab3, tab4 = st.tabs(["Patent Search", "Idea Analysis", "Detailed Comparison", "Report Generation"])
    
    # Tab 1: Patent Search
    with tab1:
        update_patent_search_tab()

    # Tab 2: Idea Analysis
    with tab2:
        st.header("Idea Analysis")
        st.write("Analyze new patent ideas and generate reports.")
        
        # Idea input form
        with st.form("idea_analysis_form"):
            idea_description = st.text_area(
                "Idea Description",
                placeholder="Enter the patent idea you want to analyze",
                height=150
            )
            
            submitted = st.form_submit_button("Analyze")
        
        # Analysis execution
        if submitted and idea_description:
            with st.spinner("Analyzing idea..."):
                try:
                    # Initialize analysis agent
                    analysis_agent = EnhancedPatentAnalysisAgent(api_key=api_key_input)
                    
                    # Analyze idea
                    analysis_result = analysis_agent.analyze_idea(idea_description)
                    
                    # Store in session state
                    st.session_state.idea_description = idea_description
                    st.session_state.analysis_result = analysis_result
                    
                    # Display results
                    if analysis_result:
                        st.success("Analysis completed successfully.")
                        
                        # Display analysis results
                        st.subheader("Analysis Results")
                        
                        # Technical features
                        st.markdown("**1. Technical Features:**")
                        for feature in analysis_result.get('technical_features', []):
                            st.markdown(f"- {feature}")
                        
                        # Improvement suggestions
                        st.markdown("**2. Improvement Suggestions:**")
                        for suggestion in analysis_result.get('improvement_suggestions', []):
                            st.markdown(f"- {suggestion}")
                        
                        # Patentability strategies
                        st.markdown("**3. Patentability Enhancement Strategies:**")
                        for strategy in analysis_result.get('patentability_strategies', []):
                            st.markdown(f"- {strategy}")
                        
                        # Technical complements
                        st.markdown("**4. Technical Complements:**")
                        for complement in analysis_result.get('technical_complements', []):
                            st.markdown(f"- {complement}")
                    else:
                        st.warning("No analysis results available.")
                except Exception as e:
                    st.error(f"Error occurred during idea analysis: {str(e)}")
                    logging.error(f"Idea analysis error: {str(e)}")
                    traceback.print_exc()
        
    # Tab 3: Detailed Comparison
    with tab3:
        st.header("Detailed Patent Comparison")
        st.write("Compare your idea with specific patents in detail.")
        
        if not ('idea_description' in st.session_state and 'search_results' in st.session_state):
            st.info("Please complete a patent search or idea analysis first to enable comparison.")
        else:
            add_comparison_feature_to_search_results(
                st.session_state.search_results,
                st.session_state.idea_description,
                api_key_input
            )
    
    # Tab 4: Report Generation
    with tab4:
        st.header("Report Generation")
        st.write("Generate final report based on patent search and idea analysis results.")
        
        # Check session state
        has_idea = 'idea_description' in st.session_state and 'analysis_result' in st.session_state
        has_patents = 'search_results' in st.session_state and st.session_state.search_results
        
        if not (has_idea or has_patents):
            st.warning("Please perform idea analysis or patent search first to generate a report.")
            return
        
        # Report generation form
        with st.form("report_generation_form"):
            st.subheader("Report Settings")
            
            # Display idea information
            if has_idea:
                st.markdown("### Analyzed Idea")
                st.markdown(f"**Idea Description:** {st.session_state.idea_description[:100]}...")
            
            # Display patent search results
            if has_patents:
                st.markdown("### Related Patent Search Results")
                st.markdown(f"**Number of Patents Found:** {len(st.session_state.search_results)}")
            
            # Report options
            include_similarity_analysis = st.checkbox("Include Similarity Analysis", value=True)
            include_appendix = st.checkbox("Include Appendix", value=True)
            
            submitted = st.form_submit_button("Generate Report")
        
        if submitted:
            with st.spinner("Generating report..."):
                try:
                    # Initialize PPT generator
                    ppt_generator = EnhancedPPTGenerator(api_key=api_key_input)
                    
                    # Create temp file
                    temp_dir = tempfile.mkdtemp()
                    output_path = os.path.join(temp_dir, f"patent_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx")
                    
                    # Generate report
                    ppt_path = ppt_generator.create_presentation(
                        idea_description=st.session_state.get('idea_description', ''),
                        patent_data=st.session_state.get('search_results', []),
                        analysis_result=st.session_state.get('analysis_result', {}),
                        output_path=output_path,
                        include_similarity=include_similarity_analysis,
                        include_appendix=include_appendix
                    )
                    
                    # Provide download
                    with open(ppt_path, 'rb') as f:
                        ppt_data = f.read()
                    
                    st.success("Report generated successfully!")
                    
                    st.download_button(
                        label="Download Report",
                        data=ppt_data,
                        file_name=f"patent_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    )
                    
                    # Show preview
                    st.subheader("Report Structure")
                    st.markdown("""
                    1. **Title**
                    2. **Executive Summary**
                    3. **Problem Statement**
                    4. **Solution Overview**
                    5. **Technical Details**
                    6. **Patent Landscape**
                    7. **Similarity Analysis** (if selected)
                    8. **Recommendations**
                    9. **Appendix** (if selected)
                    """)
                except Exception as e:
                    st.error(f"Error occurred during report generation: {str(e)}")
                    logging.error(f"Report generation error: {str(e)}")
                    traceback.print_exc()

if __name__ == "__main__":
    main()
