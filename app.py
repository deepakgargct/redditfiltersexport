import streamlit as st
import praw
import pandas as pd
from datetime import datetime, timedelta
import altair as alt
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re

# === Reddit API Setup ===
reddit = praw.Reddit(
    client_id=st.secrets["client_id"],
    client_secret=st.secrets["client_secret"],
    user_agent=st.secrets["user_agent"]
)
reddit.read_only = True

# === Helper Functions ===
def is_internal_link(post):
    return (not post.is_self and 'reddit.com' in post.url) or post.is_self

def get_reddit_posts(keyword, start_date, end_date, subreddits=None):
    posts = []
    query = f'title:"{keyword}"'
    target_subreddits = subreddits if subreddits else ["all"]

    for sub in target_subreddits:
        try:
            search_results = reddit.subreddit(sub).search(query, sort="top", limit=300, time_filter="year")
            for submission in search_results:
                created = datetime.utcfromtimestamp(submission.created_utc)
                if start_date <= created <= end_date and is_internal_link(submission):
                    title_lower = submission.title.lower()
                    if keyword.lower() in title_lower:
                        posts.append({
                            "Title": submission.title,
                            "Body": submission.selftext if submission.is_self else "",
                            "Score": submission.score,
                            "Upvote Ratio": submission.upvote_ratio,
                            "Comments": submission.num_comments,
                            "Subreddit": submission.subreddit.display_name,
                            "Permalink": f"https://reddit.com{submission.permalink}",
                            "Created": created.date()
                        })
                if len(posts) >= 100:
                    break
        except Exception as e:
            st.warning(f"Error fetching posts from r/{sub}: {e}")
    return posts

def generate_wordcloud(titles):
    text = ' '.join(titles)
    text = re.sub(r"http\S+|[^A-Za-z\s]", "", text)
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    return wordcloud

# === Streamlit UI ===
st.set_page_config(page_title="Reddit Topic Explorer", layout="wide")
st.title("🔍 Reddit Topic Explorer")

# === Inputs ===
col1, col2 = st.columns(2)
with col1:
    keyword = st.text_input("Enter a keyword to search Reddit")
with col2:
    sub_input = st.text_input("Optional: Add up to 5 subreddits separated by commas (no r/ prefix)")

selected_subreddits = [sub.strip() for sub in sub_input.split(",") if sub.strip()]
if len(selected_subreddits) > 5:
    st.error("You can specify a maximum of 5 subreddits.")
    selected_subreddits = selected_subreddits[:5]

# === Date Range ===
st.markdown("### 📆 Custom Date Range")
col3, col4 = st.columns(2)
with col3:
    start_date = st.date_input("Start Date", value=datetime.utcnow() - timedelta(days=30))
with col4:
    end_date = st.date_input("End Date", value=datetime.utcnow())

# === Fetch Posts ===
if st.button("Fetch Posts") and keyword:
    with st.spinner("Fetching top Reddit posts..."):
        posts_data = get_reddit_posts(
            keyword=keyword,
            start_date=datetime.combine(start_date, datetime.min.time()),
            end_date=datetime.combine(end_date, datetime.max.time()),
            subreddits=selected_subreddits
        )
        if posts_data:
            df = pd.DataFrame(posts_data)

            # === Filter by Subreddit ===
            subreddits = df["Subreddit"].unique().tolist()
            selected_subs = st.multiselect("Filter by Subreddit", subreddits, default=subreddits)
            df = df[df["Subreddit"].isin(selected_subs)]

            # === Filter by Comments ===
            st.markdown("### 💬 Filter by Number of Comments")
            col1, col2 = st.columns([1, 2])
            with col1:
                op = st.selectbox("Operator", options=["=", "<", "<=", ">", ">="])
            with col2:
                comment_input = st.text_input("Comment count (number only)", value="")

            # Apply comment filter only if input is a valid number
            if comment_input.isdigit():
                threshold = int(comment_input)
                if op == "=":
                    df = df[df["Comments"] == threshold]
                elif op == "<":
                    df = df[df["Comments"] < threshold]
                elif op == "<=":
                    df = df[df["Comments"] <= threshold]
                elif op == ">":
                    df = df[df["Comments"] > threshold]
                elif op == ">=":
                    df = df[df["Comments"] >= threshold]
            elif comment_input:
                st.warning("Please enter a valid integer for comment count.")

            # === Sorting ===
            sort_by = st.selectbox("Sort by", options=["Score", "Comments"])
            df = df.sort_values(by=sort_by, ascending=False)

            # === Display Data ===
            st.success(f"Found {len(df)} Reddit posts.")
            st.dataframe(df, use_container_width=True)

            # === CSV Download ===
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", data=csv, file_name=f"{keyword}_reddit_posts.csv", mime='text/csv')

            # === Bar Chart ===
            st.markdown("### 📊 Post Activity Over Time")
            chart = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("Created:T", title="Date"),
                    y=alt.Y("count()", title="Number of Posts"),
                    tooltip=["Created", "count()"]
                )
                .properties(width="container")
            )
            st.altair_chart(chart, use_container_width=True)

            # === Comment Distribution Histogram ===
            st.markdown("### 📈 Comment Distribution")
            st.bar_chart(df["Comments"])

            # === Word Cloud ===
            st.markdown("### ☁️ Word Cloud from Post Titles")
            wordcloud = generate_wordcloud(df["Title"].tolist())
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis("off")
            st.pyplot(fig)

        else:
            st.warning("No posts found. Try another keyword, subreddit, or time frame.")
