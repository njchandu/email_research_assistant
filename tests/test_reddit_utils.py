#!/usr/bin/env python3
"""Tests for reddit_utils module."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from reddit_utils import (
    search_reddit_via_scrapingfish,
    fetch_post_comments_via_scrapingfish,
    get_top_posts_with_comments,
    get_top_post_with_comments,
)


@pytest.fixture
def mock_search_response():
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "AI Agents are changing everything",
                        "permalink": "/r/LocalLLaMA/comments/abc123/ai_agents_are_changing_everything/",
                        "score": 150,
                        "num_comments": 25,
                        "subreddit": "LocalLLaMA",
                        "selftext": "This is a post about AI agents..."
                    }
                },
                {
                    "data": {
                        "title": "Building autonomous agents with LLMs",
                        "permalink": "/r/LocalLLaMA/comments/def456/building_autonomous_agents/",
                        "score": 75,
                        "num_comments": 12,
                        "subreddit": "LocalLLaMA",
                        "selftext": "Guide to building agents..."
                    }
                },
                {
                    "data": {
                        "title": "Random unrelated post",
                        "permalink": "/r/Baking/comments/xyz789/random_post/",
                        "score": 5000,
                        "num_comments": 500,
                        "subreddit": "Baking",
                        "selftext": "This should not appear for AI searches"
                    }
                }
            ]
        }
    }


@pytest.fixture
def mock_comments_response():
    return [
        {"data": {"children": [{"data": {"title": "Post title"}}]}},
        {
            "data": {
                "children": [
                    {"kind": "t1", "data": {"author": "user1", "score": 50, "body": "Great insight!"}},
                    {"kind": "t1", "data": {"author": "user2", "score": 30, "body": "I agree with this"}},
                    {"kind": "t1", "data": {"author": "user3", "score": 10, "body": "Interesting point"}},
                ]
            }
        }
    ]


class TestSearchRedditViaScrapingfish:
    @patch("reddit_utils.requests.get")
    def test_search_returns_relevant_posts(self, mock_get, mock_search_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_search_response

        results = search_reddit_via_scrapingfish("AI Agents", num_results=3)

        assert len(results) == 3
        assert all("url" in r for r in results)
        assert all("title" in r for r in results)
        assert all("score" in r for r in results)

    @patch("reddit_utils.requests.get")
    def test_search_uses_relevance_sort(self, mock_get, mock_search_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_search_response

        search_reddit_via_scrapingfish("AI Agents", num_results=3)

        call_args = mock_get.call_args
        url_param = call_args[1]["params"]["url"]
        assert "sort=relevance" in url_param, "Search should use sort=relevance to get keyword-relevant results"

    @patch("reddit_utils.requests.get")
    def test_search_with_subreddit_restriction(self, mock_get, mock_search_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_search_response

        search_reddit_via_scrapingfish("AI Agents", subreddit="LocalLLaMA", num_results=3)

        call_args = mock_get.call_args
        url_param = call_args[1]["params"]["url"]
        assert "/r/LocalLLaMA/search.json" in url_param
        assert "restrict_sr=on" in url_param

    @patch("reddit_utils.requests.get")
    def test_search_without_subreddit(self, mock_get, mock_search_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_search_response

        search_reddit_via_scrapingfish("AI Agents", subreddit=None, num_results=3)

        call_args = mock_get.call_args
        url_param = call_args[1]["params"]["url"]
        assert "/search.json?" in url_param
        assert "restrict_sr" not in url_param

    @patch("reddit_utils.requests.get")
    def test_search_sorts_by_score_locally(self, mock_get, mock_search_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_search_response

        results = search_reddit_via_scrapingfish("AI Agents", num_results=3)

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "Results should be sorted by score descending"

    @patch("reddit_utils.requests.get")
    def test_search_handles_empty_response(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"data": {"children": []}}

        results = search_reddit_via_scrapingfish("nonexistent query xyz")

        assert results == []

    @patch("reddit_utils.requests.get")
    def test_search_handles_api_error(self, mock_get):
        mock_get.side_effect = Exception("API Error")

        results = search_reddit_via_scrapingfish("AI Agents")

        assert results == []


class TestFetchPostComments:
    @patch("reddit_utils.requests.get")
    def test_fetch_comments_returns_sorted_by_score(self, mock_get, mock_comments_response):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = mock_comments_response

        comments = fetch_post_comments_via_scrapingfish("https://reddit.com/r/test/comments/abc/", num_comments=3)

        assert len(comments) == 3
        scores = [c["score"] for c in comments]
        assert scores == sorted(scores, reverse=True)

    @patch("reddit_utils.requests.get")
    def test_fetch_comments_handles_empty_response(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = []

        comments = fetch_post_comments_via_scrapingfish("https://reddit.com/r/test/comments/abc/")

        assert comments == []


class TestGetTopPostsWithComments:
    @patch("reddit_utils.fetch_post_comments_via_scrapingfish")
    @patch("reddit_utils.search_reddit_via_scrapingfish")
    def test_returns_posts_with_comments(self, mock_search, mock_comments):
        mock_search.return_value = [
            {"title": "Post 1", "url": "https://reddit.com/r/test/1", "score": 100, "num_comments": 10, "subreddit": "test", "selftext": ""}
        ]
        mock_comments.return_value = [{"author": "user1", "score": 50, "body": "Comment"}]

        results = get_top_posts_with_comments("AI Agents", num_posts=1)

        assert len(results) == 1
        assert "post" in results[0]
        assert "comments" in results[0]
        assert "keyword" in results[0]

    @patch("reddit_utils.search_reddit_via_scrapingfish")
    def test_returns_empty_when_no_posts(self, mock_search):
        mock_search.return_value = []

        results = get_top_posts_with_comments("nonexistent")

        assert results == []


class TestIntegration:
    @pytest.mark.skipif(
        not os.getenv("SCRAPINGFISH_API_KEY"),
        reason="SCRAPINGFISH_API_KEY not set"
    )
    def test_real_search_returns_relevant_results(self):
        results = search_reddit_via_scrapingfish("Agentic AI", subreddit="LocalLLaMA", num_results=3, time_filter="week")

        assert len(results) > 0, "Should return at least one result"

        for post in results:
            title_lower = post["title"].lower()
            selftext_lower = post.get("selftext", "").lower()
            subreddit = post["subreddit"].lower()

            has_ai_keyword = any(kw in title_lower or kw in selftext_lower
                                 for kw in ["ai", "agent", "llm", "model", "neural", "automation"])
            is_correct_subreddit = subreddit == "localllama"

            assert has_ai_keyword or is_correct_subreddit, \
                f"Post should be relevant: {post['title']}"

    @pytest.mark.skipif(
        not os.getenv("SCRAPINGFISH_API_KEY"),
        reason="SCRAPINGFISH_API_KEY not set"
    )
    def test_global_search_returns_keyword_relevant_results(self):
        results = search_reddit_via_scrapingfish("AI Agents", subreddit=None, num_results=5, time_filter="week")

        assert len(results) > 0, "Should return results"

        irrelevant_subreddits = {"baking", "amitheasshole", "bestofredditorupdates", "relationships"}
        found_relevant = False

        for post in results[:3]:
            subreddit_lower = post["subreddit"].lower()
            title_lower = post["title"].lower()

            if subreddit_lower not in irrelevant_subreddits:
                found_relevant = True
            if "ai" in title_lower or "agent" in title_lower:
                found_relevant = True

        assert found_relevant, \
            f"Top results should be relevant to 'AI Agents', got: {[p['subreddit'] + ': ' + p['title'][:40] for p in results[:3]]}"
