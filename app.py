import streamlit as st
import praw
import pandas as pd
from datetime import datetime, timedelta
import altair as alt
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re
from fuzzywuzzy import fuzz
import inflect
from collections import defaultdict

# === Reddit API Setup ===
reddit = praw.Reddit(
    client_id=st.secrets["client_id"],
    client_secret=st.secrets["client_secret"],
    user_agent=st.secrets["user_agent"]
)
reddit.read_only = True

# Initialize inflect engine for pluralization
p = inflect.engine()

# === Enhanced Helper Functions ===

def generate_keyword_variations(keyword):
    """Generate variations of a keyword including plurals, spacing, hyphens"""
    variations = set()
    keyword_clean = keyword.strip().lower()
    
    # Original keyword
    variations.add(keyword_clean)
    
    # Handle multi-word keywords
    words = keyword_clean.split()
    
    if len(words) > 1:
        # Add hyphenated version
        variations.add('-'.join(words))
        # Add no space version
        variations.add(''.join(words))
        
        # Generate plurals for each word and combinations
        for i, word in enumerate(words):
            plural_word = p.plural(word)
            if plural_word and plural_word != word:
                # Replace individual word with plural
                plural_words = words.copy()
                plural_words[i] = plural_word
                variations.add(' '.join(plural_words))
                variations.add('-'.join(plural_words))
                variations.add(''.join(plural_words))
    
    # Single word pluralization
    if len(words) == 1:
        plural = p.plural(keyword_clean)
        if plural and plural != keyword_clean:
            variations.add(plural)
    
    # Add variations with different spacing
    if len(words) > 1:
        # Try different combinations
        variations.add(' '.join(words))
        variations.add('_'.join(words))
    
    return list(variations)

def process_multiple_keywords(keyword_input):
    """Process multiple keywords and generate all variations"""
    if not keyword_input.strip():
        return []
    
    # Split by comma, semicolon, or newline
    keywords = re.split(r'[,;\n]+', keyword_input)
    all_variations = []
    
    for keyword in keywords:
        keyword = keyword.strip()
        if keyword:
            variations = generate_keyword_variations(keyword)
            all_variations.extend(variations)
    
    return list(set(all_variations))  # Remove duplicates

def fuzzy_match_keywords(text, keyword_variations, threshold=80):
    """Check if any keyword variations match the text using fuzzy matching"""
    text_lower = text.lower()
    
    # Direct substring matching first (faster)
    for variation in keyword_variations:
        if variation in text_lower:
            return True, variation, 100
    
    # Fuzzy matching for partial matches
    words = text_lower.split()
    for variation in keyword_variations:
        for word in words:
            ratio = fuzz.ratio(variation, word)
            if ratio >= threshold:
                return True, variation, ratio
        
        # Also check phrase matching
        ratio = fuzz.partial_ratio(variation, text_lower)
        if ratio >= threshold:
            return True, variation, ratio
    
    return False, None, 0

def calculate_marketing_relevance(post_title, post_body):
    """Calculate marketing relevance score based on buying intent and language patterns"""
    text = f"{post_title} {post_body}".lower()
    
    # High-value buying intent signals
    high_intent_phrases = [
        'looking for', 'need help', 'recommendations', 'where to buy', 'best place',
        'help me choose', 'advice needed', 'should i buy', 'worth buying',
        'comparing', 'vs', 'better option', 'alternatives', 'suggestions',
        'budget', 'price range', 'affordable', 'cheap', 'expensive',
        'quality', 'reviews', 'experience with', 'anyone tried',
        'thinking of buying', 'planning to buy', 'about to purchase',
        'custom', 'made to order', 'personalized', 'bespoke'
    ]
    
    # Medium-value research signals
    medium_intent_phrases = [
        'what do you think', 'opinions', 'thoughts', 'feedback',
        'pros and cons', 'worth it', 'good idea', 'bad idea',
        'how much', 'cost', 'pricing', 'quotes'
    ]
    
    # Low-value signals (already purchased/showing off)
    low_intent_phrases = [
        'my new', 'just got', 'finally received', 'arrived today',
        'love my', 'so happy with', 'perfect', 'exactly what i wanted',
        'couldn\'t be happier', 'amazing quality', 'here it is',
        'finally here', 'delivery', 'unboxing'
    ]
    
    # Question indicators (usually high intent)
    question_patterns = ['?', 'how', 'what', 'where', 'when', 'why', 'which', 'who']
    
    score = 0
    reasons = []
    
    # Check for high intent phrases
    for phrase in high_intent_phrases:
        if phrase in text:
            score += 3
            reasons.append(f"High intent: '{phrase}'")
    
    # Check for medium intent phrases
    for phrase in medium_intent_phrases:
        if phrase in text:
            score += 2
            reasons.append(f"Medium intent: '{phrase}'")
    
    # Penalize for low intent phrases
    for phrase in low_intent_phrases:
        if phrase in text:
            score -= 2
            reasons.append(f"Low intent: '{phrase}'")
    
    # Bonus for questions
    question_count = sum(1 for pattern in question_patterns if pattern in text)
    if question_count > 0:
        score += min(question_count, 3)  # Cap at 3 bonus points
        reasons.append(f"Question indicators: {question_count}")
    
    # Normalize score
    max_score = max(score, 0)
    
    return max_score, reasons

def categorize_marketing_potential(score):
    """Categorize posts by marketing potential"""
    if score >= 6:
        return "High"
    elif score >= 3:
        return "Medium"
    elif score >= 1:
        return "Low"
    else:
        return "Very Low"

def is_internal_link(post):
    return (not post.is_self and 'reddit.com' in post.url) or post.is_self

def get_enhanced_reddit_posts(keyword_input, start_date, end_date, subreddits=None, comment_filter=None, fuzzy_threshold=80):
    """Enhanced Reddit post fetching with keyword variations and fuzzy matching"""
    posts = []
    keyword_variations = process_multiple_keywords(keyword_input)
    
    if not keyword_variations:
        return []
    
    # Display which keywords we're searching for
    st.info(f"Searching for keyword variations: {', '.join(keyword_variations[:10])}{'...' if len(keyword_variations) > 10 else ''}")
    
    target_subreddits = subreddits if subreddits else ["all"]
    
    # Create broader search queries
    search_queries = []
    
    # Add main keyword variations to search
    for variation in keyword_variations[:5]:  # Limit to avoid too many API calls
        search_queries.append(f'title:"{variation}"')
    
    # Add intent-based searches
    intent_queries = [
        'title:"looking for"', 'title:"need help"', 'title:"recommendations"',
        'title:"help me choose"', 'title:"advice"', 'title:"suggestions"'
    ]
    search_queries.extend(intent_queries)
    
    for sub in target_subreddits:
        try:
            # Search with different queries
            for query in search_queries:
                search_results = reddit.subreddit(sub).search(query, sort="top", limit=100, time_filter="year")
                
                for submission in search_results:
                    created = datetime.utcfromtimestamp(submission.created_utc)
                    if start_date <= created <= end_date and is_internal_link(submission):
                        
                        # Enhanced matching: check title AND body
                        title_text = submission.title
                        body_text = submission.selftext if submission.is_self else ""
                        combined_text = f"{title_text} {body_text}"
                        
                        # Check for keyword matches with fuzzy matching
                        has_match, matched_keyword, match_score = fuzzy_match_keywords(
                            combined_text, keyword_variations, fuzzy_threshold
                        )
                        
                        if has_match:
                            # Apply comment filter
                            if comment_filter:
                                operator, value = comment_filter
                                if operator == "=" and not (submission.num_comments == value):
                                    continue
                                elif operator == ">" and not (submission.num_comments > value):
                                    continue
                                elif operator == ">=" and not (submission.num_comments >= value):
                                    continue
                                elif operator == "<" and not (submission.num_comments < value):
                                    continue
                                elif operator == "<=" and not (submission.num_comments <= value):
                                    continue
                            
                            # Calculate marketing relevance
                            marketing_score, relevance_reasons = calculate_marketing_relevance(title_text, body_text)
                            marketing_category = categorize_marketing_potential(marketing_score)
                            
                            posts.append({
                                "Title": title_text,
                                "Body": body_text[:500] + "..." if len(body_text) > 500 else body_text,
                                "Score": submission.score,
                                "Upvote Ratio": submission.upvote_ratio,
                                "Comments": submission.num_comments,
                                "Subreddit": submission.subreddit.display_name,
                                "Permalink": f"https://reddit.com{submission.permalink}",
                                "Created": created.date(),
                                "Matched Keyword": matched_keyword,
                                "Match Score": match_score,
                                "Marketing Score": marketing_score,
                                "Marketing Potential": marketing_category,
                                "Relevance Reasons": "; ".join(relevance_reasons) if relevance_reasons else "No specific signals"
                            })
                
                if len(posts) >= 200:  # Increased limit
                    break
            
            if len(posts) >= 200:
                break
                
        except Exception as e:
            st.warning(f"Error fetching posts from r/{sub}: {e}")
    
    # Remove duplicates based on permalink
    seen_permalinks = set()
    unique_posts = []
    for post in posts:
        if post["Permalink"] not in seen_permalinks:
            seen_permalinks.add(post["Permalink"])
            unique_posts.append(post)
    
    return unique_posts

def generate_wordcloud(titles):
    text = ' '.join(titles)
    text = re.sub(r"http\S+|[^A-Za-z\s]", "", text)  # Clean links and special chars
    if text.strip():
        wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
        return wordcloud
    return None

# === Streamlit UI ===
st.set_page_config(page_title="Enhanced Reddit Marketing Explorer", layout="wide")
st.title("🔍 Enhanced Reddit Marketing Explorer")
st.markdown("*Advanced keyword matching with marketing intent analysis*")

# === Enhanced Inputs ===
st.subheader("🎯 Keyword Configuration")
col1, col2 = st.columns(2)

with col1:
    keyword_input = st.text_area(
        "Enter keywords (one per line or comma-separated)",
        placeholder="engagement ring\ncustom ring\nwedding band\nmoissanite",
        help="Supports multiple keywords, synonyms, and automatic plural variations"
    )

with col2:
    fuzzy_threshold = st.slider(
        "Fuzzy Match Threshold", 
        min_value=60, max_value=100, value=80,
        help="Lower values catch more variations but may include irrelevant matches"
    )

# Show keyword variations preview
if keyword_input:
    variations = process_multiple_keywords(keyword_input)
    with st.expander("Preview Keyword Variations"):
        st.write(f"**{len(variations)} variations will be searched:**")
        st.write(", ".join(variations))

col3, col4 = st.columns(2)
with col3:
    sub_input = st.text_input("Optional: Subreddits (comma separated, no 'r/' prefix)")
with col4:
    marketing_filter = st.selectbox(
        "Filter by Marketing Potential", 
        options=["All", "High", "Medium", "Low", "Very Low"]
    )

selected_subreddits = [sub.strip() for sub in sub_input.split(",") if sub.strip()]
if len(selected_subreddits) > 5:
    st.error("You can specify a maximum of 5 subreddits.")
    selected_subreddits = selected_subreddits[:5]

# === Date Range Filter ===
st.subheader("📅 Date Range Filter")
col5, col6 = st.columns(2)
with col5:
    start_date = st.date_input("Start date", datetime.today() - timedelta(days=30))
with col6:
    end_date = st.date_input("End date", datetime.today())

# === Comment Count Filter ===
st.subheader("💬 Comment Count Filter")
col7, col8 = st.columns(2)
with col7:
    comment_operator = st.selectbox("Operator", options=["", "=", ">", ">=", "<", "<="])
with col8:
    comment_value = st.number_input("Number of Comments", min_value=0, step=1, value=0)

comment_filter = None
if comment_operator in ["=", ">", ">=", "<", "<="]:
    comment_filter = (comment_operator, comment_value)

# === Fetch and Display ===
if st.button("🚀 Search Reddit Posts") and keyword_input:
    with st.spinner("Fetching and analyzing Reddit posts..."):
        posts_data = get_enhanced_reddit_posts(
            keyword_input,
            start_date=datetime.combine(start_date, datetime.min.time()),
            end_date=datetime.combine(end_date, datetime.max.time()),
            subreddits=selected_subreddits,
            comment_filter=comment_filter,
            fuzzy_threshold=fuzzy_threshold
        )
        
        if posts_data:
            df = pd.DataFrame(posts_data)
            
            # Apply marketing potential filter
            if marketing_filter != "All":
                df = df[df["Marketing Potential"] == marketing_filter]
            
            # === Enhanced Filtering ===
            col9, col10 = st.columns(2)
            with col9:
                subreddits = df["Subreddit"].unique().tolist()
                selected_subs = st.multiselect("Filter by Subreddit", subreddits, default=subreddits)
                df = df[df["Subreddit"].isin(selected_subs)]
            
            with col10:
                sort_options = ["Marketing Score", "Score", "Comments", "Match Score"]
                sort_by = st.selectbox("Sort by", options=sort_options)
                df = df.sort_values(by=sort_by, ascending=False)
            
            # === Display Results ===
            st.success(f"Found {len(df)} relevant Reddit posts with marketing analysis.")
            
            # Marketing potential summary
            if len(df) > 0:
                potential_counts = df["Marketing Potential"].value_counts()
                col11, col12, col13, col14 = st.columns(4)
                with col11:
                    st.metric("High Potential", potential_counts.get("High", 0))
                with col12:
                    st.metric("Medium Potential", potential_counts.get("Medium", 0))
                with col13:
                    st.metric("Low Potential", potential_counts.get("Low", 0))
                with col14:
                    st.metric("Very Low Potential", potential_counts.get("Very Low", 0))
            
            # Display data with enhanced columns
            display_columns = [
                "Title", "Marketing Potential", "Marketing Score", "Subreddit", 
                "Score", "Comments", "Matched Keyword", "Match Score", "Created", 
                "Relevance Reasons", "Permalink"
            ]
            st.dataframe(df[display_columns], use_container_width=True)
            
            # === CSV Download ===
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Enhanced CSV", 
                data=csv, 
                file_name=f"enhanced_reddit_marketing_analysis.csv", 
                mime='text/csv'
            )
            
            # === Enhanced Visualizations ===
            col15, col16 = st.columns(2)
            
            with col15:
                st.subheader("📊 Marketing Potential Distribution")
                potential_chart = (
                    alt.Chart(df)
                    .mark_bar()
                    .encode(
                        x=alt.X("Marketing Potential:N", title="Marketing Potential"),
                        y=alt.Y("count()", title="Number of Posts"),
                        color=alt.Color(
                            "Marketing Potential:N",
                            scale=alt.Scale(range=["#d73027", "#fc8d59", "#fee08b", "#e0f3f8"])
                        ),
                        tooltip=["Marketing Potential", "count()"]
                    )
                    .properties(width="container")
                )
                st.altair_chart(potential_chart, use_container_width=True)
            
            with col16:
                st.subheader("📈 Post Activity Over Time")
                time_chart = (
                    alt.Chart(df)
                    .mark_bar()
                    .encode(
                        x=alt.X("Created:T", title="Date"),
                        y=alt.Y("count()", title="Number of Posts"),
                        color=alt.Color("Marketing Potential:N"),
                        tooltip=["Created", "count()", "Marketing Potential"]
                    )
                    .properties(width="container")
                )
                st.altair_chart(time_chart, use_container_width=True)
            
            # === Word Cloud ===
            st.subheader("☁️ Word Cloud from High-Potential Post Titles")
            high_potential_posts = df[df["Marketing Potential"].isin(["High", "Medium"])]
            if len(high_potential_posts) > 0:
                wordcloud = generate_wordcloud(high_potential_posts["Title"].tolist())
                if wordcloud:
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.imshow(wordcloud, interpolation='bilinear')
                    ax.axis("off")
                    st.pyplot(fig)
            else:
                st.info("No high or medium potential posts found for word cloud generation.")
        
        else:
            st.warning("No posts found. Try different keywords, subreddits, or adjust the fuzzy match threshold.")

# === Help Section ===
with st.expander("ℹ️ How to Use This Enhanced Tool"):
    st.markdown("""
    ### Key Features:
    
    **🔤 Smart Keyword Matching:**
    - Automatically generates plural/singular variations
    - Handles different spacing and hyphenation
    - Supports multiple keywords and synonyms
    - Uses fuzzy matching to catch variations
    
    **🎯 Marketing Intent Analysis:**
    - Identifies buying intent signals ("looking for", "need help")
    - Scores posts by marketing potential
    - Filters out "showing off" posts
    - Highlights research and decision-making posts
    
    **📊 Enhanced Search:**
    - Searches both titles AND post bodies
    - Combines keyword and intent-based searches
    - Removes duplicate posts automatically
    - Provides detailed match information
    
    **💡 Tips:**
    - Use synonyms and related terms for better coverage
    - Lower fuzzy threshold catches more variations
    - Focus on "High" and "Medium" potential posts for marketing
    - Check "Relevance Reasons" to understand why posts were scored
    """)
