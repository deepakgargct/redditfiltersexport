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
                            "Body": submission.selftext,
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
    text = re.sub(r"http\S+|[^A-Za-z\s]", "", text)  # Clean links and special chars
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    return wordcloud

# === Streamlit UI ===
st.set_page_config(page_title="Reddit Topic Explorer", layout="wide")
st.title("🔍 Reddit Topic Explorer")

# === Inputs ===
keyword = st.text_input("Enter a keyword to search Reddit")

st.markdown("### 📅 Select Custom Date Range")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date", value=datetime.utcnow().date() - timedelta(days=30))
with col2:
    end_date = st.date_input("End Date", value=datetime.utcnow().date())

sub_input = st.text_input("Optional: Add up to 5 subreddits (comma-separated, no r/)")
selected_subreddits = [sub.strip() for sub in sub_input.split(",") if sub.strip()]
if len(selected_subreddits) > 5:
    st.error("You can specify a maximum of 5 subreddits.")
    selected_subreddits = selected_subreddits[:5]

# === Fetch & Display ===
if st.button("Fetch Posts") and keyword:
    if start_date > end_date:
        st.error("Start date must be earlier than end date.")
    else:
        with st.spinner("Fetching Reddit posts..."):
            posts_data = get_reddit_posts(
                keyword,
                datetime.combine(start_date, datetime.min.time()),
                datetime.combine(end_date, datetime.max.time()),
                selected_subreddits
            )
            if posts_data:
                df = pd.DataFrame(posts_data)

                # === Filter by Subreddit ===
                subs = df["Subreddit"].unique().tolist()
                selected_subs = st.multiselect("Filter by Subreddit", subs, default=subs)
                df = df[df["Subreddit"].isin(selected_subs)]

                # === Filter by Comments ===
                st.markdown("### 💬 Filter by Number of Comments")
                col1, col2 = st.columns([1, 2])
                with col1:
                    op = st.selectbox("Operator", options=["=", "<", "<=", ">", ">="])
                with col2:
                    try:
                        threshold = int(st.text_input("Comment count"))
                    except:
                        threshold = None

                if threshold is not None:
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

                # === Sort Posts ===
                sort_by = st.selectbox("Sort by", options=["Score", "Comments"])
                df = df.sort_values(by=sort_by, ascending=False)

                # === Display Table ===
                st.success(f"Found {len(df)} Reddit posts.")
                st.dataframe(df, use_container_width=True)

                # === Download CSV ===
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download CSV", data=csv, file_name=f"{keyword}_reddit_posts.csv", mime='text/csv')

                # === Chart: Posts Over Time ===
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

                # === Chart: Comment Distribution ===
                st.markdown("### 📈 Comment Count Distribution")
                hist_chart = (
                    alt.Chart(df)
                    .mark_bar()
                    .encode(
                        alt.X("Comments:Q", bin=alt.Bin(maxbins=30), title="Number of Comments"),
                        alt.Y("count()", title="Number of Posts"),
                        tooltip=["count()"]
                    )
                    .properties(width="container")
                )
                st.altair_chart(hist_chart, use_container_width=True)

                # === Word Cloud ===
                st.markdown("### ☁️ Word Cloud from Post Titles")
                wordcloud = generate_wordcloud(df["Title"].tolist())
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.imshow(wordcloud, interpolation='bilinear')
                ax.axis("off")
                st.pyplot(fig)
            else:
                st.warning("No posts found. Try a different keyword, subreddit, or date range.")
