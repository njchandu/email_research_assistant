#!/usr/bin/env python3
"""Reddit utilities for searching and fetching posts with comments via Serper."""

import logging
import os
import requests
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

REDDIT_HEADERS = {
    "User-Agent": "python:daily-insights:v1.0 (by /u/chandan_insights)",
    "Accept": "application/json",
}


def search_reddit_via_serper(
    keyword: str,
    subreddit: Optional[str] = None,
    num_results: int = 5
) -> list[dict]:
    logger.info(f"[REDDIT] Searching Reddit via Serper for '{keyword}' (subreddit={subreddit or 'all'})")

    if subreddit:
        query = f"site:reddit.com/r/{subreddit} {keyword}"
    else:
        query = f"site:reddit.com {keyword}"

    url = "https://google.serper.dev/search"
    payload = {
        "q": query,
        "num": num_results,
    }
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY"),
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"[REDDIT] Serper search failed: {e}")
        return []

    posts = []
    for item in data.get("organic", []):
        link = item.get("link", "")
        if "/comments/" in link:
            posts.append({
                "title": item.get("title", ""),
                "url": link,
                "snippet": item.get("snippet", ""),
            })

    logger.info(f"[REDDIT] Found {len(posts)} Reddit posts via Serper")
    return posts


def fetch_post_comments(post_url: str, num_comments: int = 5) -> tuple[dict, list[dict]]:
    json_url = post_url.rstrip("/") + ".json"
    logger.info(f"[REDDIT] Fetching comments from: {post_url}")

    try:
        response = requests.get(json_url, headers=REDDIT_HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"[REDDIT] Failed to fetch comments: {e}")
        return {}, []

    post_data = data[0]["data"]["children"][0]["data"]
    post = {
        "title": post_data.get("title", ""),
        "url": post_url,
        "score": post_data.get("score", 0),
        "num_comments": post_data.get("num_comments", 0),
        "subreddit": post_data.get("subreddit", ""),
        "selftext": post_data.get("selftext", "")[:500],
    }

    comments = []
    if len(data) > 1:
        raw_comments = data[1]["data"]["children"]
        logger.info(f"[REDDIT] Found {len(raw_comments)} raw comments")
        for child in raw_comments:
            if child["kind"] == "t1":
                comment_data = child["data"]
                comments.append({
                    "author": comment_data.get("author", "[deleted]"),
                    "score": comment_data.get("score", 0),
                    "body": comment_data.get("body", "")[:500],
                })

    comments_sorted = sorted(comments, key=lambda x: x["score"], reverse=True)
    top_comments = comments_sorted[:num_comments]
    logger.info(f"[REDDIT] Returning top {len(top_comments)} comments (sorted by score)")
    return post, top_comments


def get_top_post_with_comments(
    keyword: str,
    subreddit: Optional[str] = None,
    num_comments: int = 5
) -> Optional[dict]:
    logger.info(f"[REDDIT] === Processing keyword: '{keyword}' (subreddit={subreddit or 'all'}) ===")

    posts = search_reddit_via_serper(keyword, subreddit=subreddit, num_results=3)

    if not posts:
        logger.warning(f"[REDDIT] No results for '{keyword}', skipping")
        return None

    for post in posts:
        try:
            post_details, comments = fetch_post_comments(post["url"], num_comments=num_comments)
            if post_details and comments:
                result = {
                    "keyword": keyword,
                    "subreddit_filter": subreddit,
                    "post": post_details,
                    "comments": comments
                }
                logger.info(f"[REDDIT] === Done with '{keyword}': post + {len(comments)} comments ===\n")
                return result
        except Exception as e:
            logger.warning(f"[REDDIT] Failed to fetch post {post['url']}: {e}")
            continue

    logger.warning(f"[REDDIT] Could not fetch any posts for '{keyword}'")
    return None


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    result = get_top_post_with_comments("claude ai", num_comments=3)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No results found")
