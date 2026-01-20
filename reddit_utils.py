#!/usr/bin/env python3
"""Reddit utilities for searching and fetching posts with comments via ScrapingFish proxy."""

import logging
import os
import time
import urllib.parse
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


def search_reddit_via_scrapingfish(
    keyword: str,
    subreddit: Optional[str] = None,
    num_results: int = 5,
    time_filter: str = "day"
) -> list[dict]:
    """Search Reddit for top posts using ScrapingFish proxy.

    Args:
        keyword: Search term
        subreddit: Optional subreddit to restrict search to
        num_results: Number of posts to return
        time_filter: Time filter (hour, day, week, month, year, all)
    """
    logger.info(f"[REDDIT] Searching Reddit for '{keyword}' (subreddit={subreddit or 'all'}, sort=top, t={time_filter})")

    encoded_keyword = urllib.parse.quote(keyword)

    if subreddit:
        reddit_url = f"https://www.reddit.com/r/{subreddit}/search.json?q={encoded_keyword}&restrict_sr=on&sort=relevance&t={time_filter}&type=link&limit={num_results + 10}"
    else:
        reddit_url = f"https://www.reddit.com/search.json?q={encoded_keyword}&sort=relevance&t={time_filter}&type=link&limit={num_results + 10}"

    payload = {
        "api_key": os.getenv("SCRAPINGFISH_API_KEY"),
        "url": reddit_url,
    }

    try:
        response = requests.get("https://scraping.narf.ai/api/v1/", params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"[REDDIT] ScrapingFish search failed: {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        post_data = child.get("data", {})
        permalink = post_data.get("permalink", "")
        if permalink:
            posts.append({
                "title": post_data.get("title", ""),
                "url": f"https://www.reddit.com{permalink}",
                "score": post_data.get("score", 0),
                "num_comments": post_data.get("num_comments", 0),
                "subreddit": post_data.get("subreddit", ""),
                "selftext": post_data.get("selftext", "")[:500],
            })

    posts.sort(key=lambda x: x["score"], reverse=True)
    posts = posts[:num_results]

    logger.info(f"[REDDIT] Found {len(posts)} top Reddit posts via ScrapingFish")
    return posts


def fetch_post_comments_via_scrapingfish(post_url: str, num_comments: int = 5) -> list[dict]:
    """Fetch comments for a Reddit post using ScrapingFish proxy."""
    json_url = post_url.rstrip("/") + ".json"
    logger.info(f"[REDDIT] Fetching comments from: {post_url}")

    payload = {
        "api_key": os.getenv("SCRAPINGFISH_API_KEY"),
        "url": json_url,
    }

    try:
        response = requests.get("https://scraping.narf.ai/api/v1/", params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"[REDDIT] Failed to fetch comments: {e}")
        return []

    if not data or len(data) < 2:
        logger.warning("[REDDIT] No comments data in response")
        return []

    try:
        comments = []
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
        return top_comments
    except (KeyError, IndexError) as e:
        logger.error(f"[REDDIT] Failed to parse comments: {e}")
        return []


def fetch_post_by_url(post_url: str, num_comments: int = 10) -> Optional[dict]:
    """Fetch a Reddit post and its comments by URL using ScrapingFish proxy.

    Args:
        post_url: Full Reddit post URL
        num_comments: Number of top comments to return (default: 10)

    Returns:
        Dict with post details and comments, or None on failure
    """
    json_url = post_url.rstrip("/") + ".json"
    logger.info(f"[REDDIT] Fetching post: {post_url}")

    payload = {
        "api_key": os.getenv("SCRAPINGFISH_API_KEY"),
        "url": json_url,
    }

    try:
        response = requests.get("https://scraping.narf.ai/api/v1/", params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"[REDDIT] Failed to fetch post: {e}")
        return None

    if not data or len(data) < 1:
        logger.warning("[REDDIT] No post data in response")
        return None

    try:
        post_data = data[0]["data"]["children"][0]["data"]

        result = {
            "title": post_data.get("title", ""),
            "author": post_data.get("author", "[deleted]"),
            "subreddit": post_data.get("subreddit", ""),
            "score": post_data.get("score", 0),
            "upvote_ratio": post_data.get("upvote_ratio", 0),
            "num_comments": post_data.get("num_comments", 0),
            "created_utc": post_data.get("created_utc", 0),
            "url": post_url,
            "selftext": post_data.get("selftext", ""),
            "link_url": post_data.get("url", ""),
            "is_self": post_data.get("is_self", True),
            "comments": []
        }

        if len(data) >= 2:
            comments = []
            raw_comments = data[1]["data"]["children"]
            logger.info(f"[REDDIT] Found {len(raw_comments)} raw comments")

            for child in raw_comments:
                if child["kind"] == "t1":
                    comment_data = child["data"]
                    comments.append({
                        "author": comment_data.get("author", "[deleted]"),
                        "score": comment_data.get("score", 0),
                        "body": comment_data.get("body", ""),
                    })

            comments_sorted = sorted(comments, key=lambda x: x["score"], reverse=True)
            result["comments"] = comments_sorted[:num_comments]

        logger.info(f"[REDDIT] Fetched: '{result['title'][:50]}...' ({result['score']} pts, {len(result['comments'])} comments)")
        return result

    except (KeyError, IndexError) as e:
        logger.error(f"[REDDIT] Failed to parse post: {e}")
        return None


def get_top_posts_with_comments(
    keyword: str,
    subreddit: Optional[str] = None,
    num_posts: int = 3,
    num_comments: int = 5,
    time_filter: str = "day"
) -> list[dict]:
    """Fetch top-voted posts with comments for a keyword using ScrapingFish.

    Args:
        keyword: Search term
        subreddit: Optional subreddit to restrict search to
        num_posts: Number of posts to return
        num_comments: Number of top comments per post
        time_filter: Time filter (hour, day, week, month, year, all)
    """
    logger.info(f"[REDDIT] === Processing keyword: '{keyword}' (subreddit={subreddit or 'all'}, num_posts={num_posts}, t={time_filter}) ===")

    posts = search_reddit_via_scrapingfish(keyword, subreddit=subreddit, num_results=num_posts, time_filter=time_filter)

    if not posts:
        logger.warning(f"[REDDIT] No results for '{keyword}', skipping")
        return []

    results = []
    for post in posts:
        try:
            time.sleep(0.5)
            comments = fetch_post_comments_via_scrapingfish(post["url"], num_comments=num_comments)

            result = {
                "keyword": keyword,
                "subreddit_filter": subreddit,
                "post": post,
                "comments": comments
            }
            results.append(result)
            logger.info(f"[REDDIT] Got post: {post.get('title', '')[:50]}... ({post.get('score', 0)} upvotes, {len(comments)} comments)")
        except Exception as e:
            logger.warning(f"[REDDIT] Failed to fetch comments for {post['url']}: {e}")
            results.append({
                "keyword": keyword,
                "subreddit_filter": subreddit,
                "post": post,
                "comments": []
            })

    logger.info(f"[REDDIT] === Done with '{keyword}': {len(results)} posts ===\n")
    return results


def get_top_post_with_comments(
    keyword: str,
    subreddit: Optional[str] = None,
    num_comments: int = 5
) -> Optional[dict]:
    """Legacy function - returns single top post."""
    results = get_top_posts_with_comments(keyword, subreddit, num_posts=1, num_comments=num_comments)
    return results[0] if results else None


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    results = get_top_posts_with_comments("agentic AI", num_posts=3, num_comments=3, time_filter="day")
    print(json.dumps(results, indent=2))
