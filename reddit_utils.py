#!/usr/bin/env python3
"""Reddit utilities for searching and fetching posts with comments."""

import logging
import requests
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "python:daily-insights:v1.0 (by /u/chandan_insights)",
    "Accept": "application/json",
}


def search_reddit(
    keyword: str,
    subreddit: Optional[str] = None,
    sort: str = "top",
    time_filter: str = "day",
    limit: int = 5
) -> list[dict]:
    if subreddit:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": keyword,
            "sort": sort,
            "t": time_filter,
            "restrict_sr": 1,
            "limit": limit
        }
        logger.info(f"[REDDIT] Searching r/{subreddit} for '{keyword}' (sort={sort}, t={time_filter})")
    else:
        url = "https://www.reddit.com/search.json"
        params = {
            "q": keyword,
            "sort": sort,
            "t": time_filter,
            "limit": limit
        }
        logger.info(f"[REDDIT] Searching all Reddit for '{keyword}' (sort={sort}, t={time_filter})")

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        logger.debug(f"[REDDIT] Request URL: {response.url}")
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"[REDDIT] Request failed for '{keyword}': {e}")
        return []
    except ValueError as e:
        logger.error(f"[REDDIT] JSON parse failed for '{keyword}': {e}")
        return []

    posts = []
    children = data.get("data", {}).get("children", [])
    logger.info(f"[REDDIT] Found {len(children)} raw results for '{keyword}'")

    for child in children:
        post_data = child.get("data", {})
        posts.append({
            "title": post_data.get("title", ""),
            "url": f"https://www.reddit.com{post_data.get('permalink', '')}",
            "score": post_data.get("score", 0),
            "num_comments": post_data.get("num_comments", 0),
            "subreddit": post_data.get("subreddit", ""),
            "selftext": post_data.get("selftext", ""),
            "created_utc": post_data.get("created_utc", 0),
        })

    sorted_posts = sorted(posts, key=lambda x: x["score"], reverse=True)
    if sorted_posts:
        logger.info(f"[REDDIT] Top result: '{sorted_posts[0]['title'][:60]}...' (score={sorted_posts[0]['score']})")
    return sorted_posts


def fetch_post_comments(post_url: str, num_comments: int = 5) -> list[dict]:
    json_url = post_url.rstrip("/") + ".json"
    logger.info(f"[REDDIT] Fetching comments from: {post_url}")

    try:
        response = requests.get(json_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"[REDDIT] Failed to fetch comments: {e}")
        return []
    except ValueError as e:
        logger.error(f"[REDDIT] JSON parse failed for comments: {e}")
        return []

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
    for i, c in enumerate(top_comments, 1):
        logger.debug(f"[REDDIT]   #{i} u/{c['author']} (score={c['score']}): {c['body'][:50]}...")
    return top_comments


def get_top_post_with_comments(
    keyword: str,
    subreddit: Optional[str] = None,
    num_comments: int = 5,
    time_filter: str = "day"
) -> Optional[dict]:
    logger.info(f"[REDDIT] === Processing keyword: '{keyword}' (subreddit={subreddit or 'all'}) ===")

    posts = search_reddit(keyword, subreddit=subreddit, time_filter=time_filter, limit=1)

    if not posts:
        logger.warning(f"[REDDIT] No results for '{keyword}' with t={time_filter}, skipping")
        return None

    top_post = posts[0]
    logger.info(f"[REDDIT] Selected post: '{top_post['title'][:60]}...' from r/{top_post['subreddit']}")

    comments = fetch_post_comments(top_post["url"], num_comments=num_comments)

    result = {
        "keyword": keyword,
        "subreddit_filter": subreddit,
        "post": top_post,
        "comments": comments
    }
    logger.info(f"[REDDIT] === Done with '{keyword}': post + {len(comments)} comments ===\n")
    return result


if __name__ == "__main__":
    import json
    result = get_top_post_with_comments("claude ai", num_comments=3)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No results found")
