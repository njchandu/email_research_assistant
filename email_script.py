#!/usr/bin/env python3
"""
Email script for generating and sending AI research summaries.

Usage:
  python email_script.py          # Full run (all topics + Reddit)
  python email_script.py --quick  # Quick test (1 topic + 1 Reddit keyword)
  python email_script.py --dry-run  # Generate email but don't send
"""

from __future__ import print_function
import http.client
http.client._MAXHEADERS = 500

import argparse
import json
import logging
import os
import pathlib
import re
from typing import List, Dict, Any, Literal, Annotated

import requests
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
import resend

from reddit_utils import get_top_post_with_comments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

SEARCH_CONFIG = {
    "topics": [
        {"term": "Agentic AI", "category": "Agentic AI"},
        {"term": "H1B visa news", "category": "H1B / Immigration"},
        {"term": "S&P 500 market today", "category": "Markets & Finance"},
        {"term": "GitHub trending repos", "category": "GitHub / Developer Tools"},
    ],
    "reddit_keywords": [
        {"keyword": "claude ai", "subreddit": None},
        {"keyword": "local llm", "subreddit": "LocalLLaMA"},
    ]
}

QUICK_CONFIG = {
    "topics": [
        {"term": "Agentic AI", "category": "Agentic AI"},
    ],
    "reddit_keywords": [
        {"keyword": "claude ai", "subreddit": None},
    ]
}

required_environment_variables = [
    "SERPER_API_KEY",
    "SCRAPINGFISH_API_KEY",
    "RESEND_API_KEY",
    "OPENAI_API_KEY",
    "DESTINATION_EMAIL"
]


def validate_environment_variables():
    for var in required_environment_variables:
        if os.getenv(var) is None:
            raise ValueError(f"Environment variable {var} is not set")


class ResultRelevance(BaseModel):
    explanation: str
    id: str


class RelevanceCheckOutput(BaseModel):
    relevant_results: List[ResultRelevance]


class State(TypedDict):
    messages: Annotated[list, add_messages]
    summaries: List[dict]
    reddit_data: List[dict]
    approved: bool
    created_summaries: Annotated[List[dict], Field(description="The summaries created by the summariser")]
    email_template: str


class SummariserOutput(BaseModel):
    email_summary: str = Field(description="The summary email of the content")
    message: str = Field(description="A message to the reviewer requesting feedback")


class ReviewerOutput(BaseModel):
    approved: bool = Field(description="Whether the summary is approved")
    message: str = Field(description="Feedback message from the reviewer")


def search_serper(search_query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    logger.info(f"[SERPER] Searching for: '{search_query}'")
    url = "https://google.serper.dev/search"

    payload = json.dumps({
        "q": search_query,
        "gl": "gb",
        "num": num_results,
        "tbs": "qdr:d"
    })

    headers = {
        'X-API-KEY': os.getenv("SERPER_API_KEY"),
        'Content-Type': 'application/json'
    }

    response = requests.post(url, headers=headers, data=payload)
    results = response.json()

    if 'organic' not in results:
        logger.warning(f"[SERPER] No organic results for '{search_query}'")
        return []

    results_list = results['organic']
    logger.info(f"[SERPER] Found {len(results_list)} results for '{search_query}'")

    return [
        {
            'title': result['title'],
            'link': result['link'],
            'snippet': result['snippet'],
            'search_term': search_query,
            'id': idx
        }
        for idx, result in enumerate(results_list, 1)
    ]


def load_prompt(prompt_name: str) -> str:
    with open(f"prompts/{prompt_name}.md", "r") as file:
        return file.read()


def check_search_relevance(search_results: Dict[str, Any], max_results: int = 3) -> RelevanceCheckOutput:
    logger.info(f"[RELEVANCE] Checking relevance of {len(search_results)} results")
    prompt = load_prompt("relevance_check")
    prompt_template = ChatPromptTemplate.from_messages([("system", prompt)])
    llm = ChatOpenAI(model="gpt-4o-mini").with_structured_output(RelevanceCheckOutput)

    result = (prompt_template | llm).invoke({'input_search_results': search_results})
    result.relevant_results = result.relevant_results[:max_results]
    logger.info(f"[RELEVANCE] Selected {len(result.relevant_results)} relevant results")
    return result


def convert_html_to_markdown(html_content: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')

    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        level = int(h.name[1])
        h.replace_with('#' * level + ' ' + h.get_text() + '\n\n')

    for a in soup.find_all('a'):
        href = a.get('href', '')
        text = a.get_text()
        if href and text:
            a.replace_with(f'[{text}]({href})')

    for tag, marker in [
        (['b', 'strong'], '**'),
        (['i', 'em'], '*')
    ]:
        for element in soup.find_all(tag):
            element.replace_with(f'{marker}{element.get_text()}{marker}')

    for ul in soup.find_all('ul'):
        for li in ul.find_all('li'):
            li.replace_with(f'- {li.get_text()}\n')

    for ol in soup.find_all('ol'):
        for i, li in enumerate(ol.find_all('li'), 1):
            li.replace_with(f'{i}. {li.get_text()}\n')

    text = soup.get_text()
    return re.sub(r'\n\s*\n', '\n\n', text).strip()


def scrape_and_save_markdown(relevant_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pathlib.Path("scraped_markdown").mkdir(exist_ok=True)
    markdown_contents = []

    for i, result in enumerate(relevant_results):
        if 'link' not in result:
            continue

        logger.info(f"[SCRAPE] ({i+1}/{len(relevant_results)}) Scraping: {result['link'][:60]}...")

        payload = {
            "api_key": os.getenv("SCRAPINGFISH_API_KEY"),
            "url": result['link'],
            "render_js": "true"
        }

        try:
            response = requests.get("https://scraping.narf.ai/api/v1/", params=payload, timeout=30)
            if response.status_code != 200:
                logger.warning(f"[SCRAPE] Failed {result['link']}: Status {response.status_code}")
                continue

            filename = f"{result.get('id', hash(result['link']))}.md"
            filepath = os.path.join("scraped_markdown", filename)

            markdown_content = convert_html_to_markdown(response.content.decode())

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(markdown_content)

            markdown_contents.append({
                'url': result['link'],
                'filepath': filepath,
                'markdown': markdown_content,
                'title': result.get('title', ''),
                'id': result.get('id', ''),
                'category': result.get('category', 'General')
            })
            logger.info(f"[SCRAPE] Saved: {filepath}")

        except Exception as e:
            logger.error(f"[SCRAPE] Error scraping {result['link']}: {e}")

    logger.info(f"[SCRAPE] Successfully scraped {len(markdown_contents)} pages")
    return markdown_contents


def generate_summaries(markdown_contents: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    pathlib.Path("markdown_summaries").mkdir(exist_ok=True)
    summary_prompt = load_prompt("summarise_markdown_page")
    summary_template = ChatPromptTemplate.from_messages([("system", summary_prompt)])
    llm = ChatOpenAI(model="gpt-4o-mini")
    summary_chain = summary_template | llm

    summaries = []
    for i, content in enumerate(markdown_contents):
        logger.info(f"[SUMMARIZE] ({i+1}/{len(markdown_contents)}) Summarizing: {content['title'][:50]}...")
        try:
            summary = summary_chain.invoke({
                'markdown_input': ' '.join(content['markdown'].split()[:2000])
            })

            summary_filename = f"summary_{content['id']}.md"
            summary_filepath = os.path.join("markdown_summaries", summary_filename)

            with open(summary_filepath, 'w', encoding='utf-8') as f:
                f.write(summary.content)

            summaries.append({
                'markdown_summary': summary.content,
                'url': content['url'],
                'title': content['title'],
                'category': content.get('category', 'General')
            })
            logger.info(f"[SUMMARIZE] Done: {content['title'][:50]}...")

        except Exception as e:
            logger.error(f"[SUMMARIZE] Failed {content['filepath']}: {e}")

    logger.info(f"[SUMMARIZE] Generated {len(summaries)} summaries")
    return summaries


def fetch_reddit_data(reddit_config: List[Dict], num_comments: int = 5) -> List[Dict]:
    logger.info(f"[REDDIT] Fetching data for {len(reddit_config)} keywords")
    reddit_data = []

    for item in reddit_config:
        result = get_top_post_with_comments(
            keyword=item["keyword"],
            subreddit=item.get("subreddit"),
            num_comments=num_comments
        )
        if result:
            reddit_data.append(result)
        else:
            logger.warning(f"[REDDIT] No results for keyword: {item['keyword']}")

    logger.info(f"[REDDIT] Fetched {len(reddit_data)} Reddit posts with comments")
    return reddit_data


def summariser(state: State) -> Dict:
    logger.info("[GRAPH] Running summariser node")
    reddit_data = state.get("reddit_data", [])
    logger.info(f"[GRAPH] Reddit data count: {len(reddit_data)}")
    if reddit_data:
        logger.info(f"[GRAPH] Reddit keywords: {[r.get('keyword') for r in reddit_data]}")
    else:
        logger.warning("[GRAPH] No Reddit data provided to summariser!")

    summariser_output = llm_summariser.invoke({
        "messages": state["messages"],
        "list_of_summaries": state["summaries"],
        "reddit_data": json.dumps(reddit_data, indent=2),
        "input_template": state["email_template"]
    })
    new_messages = [
        AIMessage(content=summariser_output.email_summary),
        AIMessage(content=summariser_output.message)
    ]
    logger.info("[GRAPH] Summariser complete")
    return {
        "messages": new_messages,
        "created_summaries": [summariser_output.email_summary]
    }


def reviewer(state: State) -> Dict:
    logger.info("[GRAPH] Running reviewer node")
    converted_messages = [
        HumanMessage(content=msg.content) if isinstance(msg, AIMessage)
        else AIMessage(content=msg.content) if isinstance(msg, HumanMessage)
        else msg
        for msg in state["messages"]
    ]

    state["messages"] = converted_messages
    reviewer_output = llm_reviewer.invoke({"messages": state["messages"]})

    logger.info(f"[GRAPH] Reviewer decision: approved={reviewer_output.approved}")
    return {
        "messages": [HumanMessage(content=reviewer_output.message)],
        "approved": reviewer_output.approved
    }


def conditional_edge(state: State) -> Literal["summariser", END]:
    return END if state["approved"] else "summariser"


def send_email(email_content: str):
    from datetime import datetime

    logger.info("[EMAIL] Sending email via Resend")

    resend.api_key = os.getenv("RESEND_API_KEY")
    destination = os.getenv("DESTINATION_EMAIL")

    subject = f"Chandan's Daily Insights - {datetime.now().strftime('%Y-%m-%d')}"

    try:
        params: resend.Emails.SendParams = {
            "from": "Chandan's Daily Insights <onboarding@resend.dev>",
            "to": [destination],
            "subject": subject,
            "html": email_content,
        }
        response = resend.Emails.send(params)
        logger.info(f"[EMAIL] Sent successfully: {response}")
    except Exception as e:
        logger.error(f"[EMAIL] Failed to send: {e}")


def main():
    parser = argparse.ArgumentParser(description="Generate and send AI research email digest")
    parser.add_argument("--quick", action="store_true", help="Quick test mode (1 topic + 1 Reddit keyword)")
    parser.add_argument("--dry-run", action="store_true", help="Generate email but don't send")
    parser.add_argument("--max-results", type=int, default=3, help="Max results per topic (default: 3)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=False)

    logger.info("=" * 60)
    logger.info(f"[MAIN] Starting email script (quick={args.quick}, dry_run={args.dry_run})")
    logger.info("=" * 60)

    validate_environment_variables()
    logger.info("[MAIN] Environment validated")

    config = QUICK_CONFIG if args.quick else SEARCH_CONFIG
    logger.info(f"[MAIN] Using config: {len(config['topics'])} topics, {len(config['reddit_keywords'])} Reddit keywords")

    relevant_results = []
    for topic in config["topics"]:
        logger.info(f"[MAIN] Processing topic: {topic['term']}")
        results = search_serper(topic["term"], num_results=10 if not args.quick else 5)

        for r in results:
            r['category'] = topic['category']

        filtered_results = check_search_relevance(results, max_results=args.max_results)
        relevant_ids = [r.id for r in filtered_results.relevant_results]
        filtered_results = [r for r in results if str(r['id']) in relevant_ids]
        relevant_results.extend(filtered_results)

    logger.info(f"[MAIN] Total relevant results: {len(relevant_results)}")

    markdown_contents = scrape_and_save_markdown(relevant_results)
    summaries = generate_summaries(markdown_contents)

    reddit_data = fetch_reddit_data(
        config["reddit_keywords"],
        num_comments=5 if not args.quick else 3
    )

    logger.info("[MAIN] Setting up LLM workflow")
    llm = ChatOpenAI(model="gpt-4o-mini")

    with open("email_template.md", "r") as f:
        email_template = f.read()

    summariser_prompt = ChatPromptTemplate.from_messages([
        ("system", load_prompt("summariser")),
        ("placeholder", "{messages}"),
    ])

    reviewer_prompt = ChatPromptTemplate.from_messages([
        ("system", load_prompt("reviewer")),
        ("placeholder", "{messages}"),
    ])

    global llm_summariser, llm_reviewer
    llm_summariser = summariser_prompt | llm.with_structured_output(SummariserOutput)
    llm_reviewer = reviewer_prompt | llm.with_structured_output(ReviewerOutput)

    graph_builder = StateGraph(State)
    graph_builder.add_node("summariser", summariser)
    graph_builder.add_node("reviewer", reviewer)
    graph_builder.add_edge(START, "summariser")
    graph_builder.add_edge("summariser", "reviewer")
    graph_builder.add_conditional_edges('reviewer', conditional_edge)

    graph = graph_builder.compile()

    logger.info("[MAIN] Running graph")
    output = graph.invoke({
        "summaries": summaries,
        "reddit_data": reddit_data,
        "email_template": email_template
    })

    final_email = output["created_summaries"][-1]
    logger.info(f"[MAIN] Generated email ({len(final_email)} chars)")

    if args.dry_run:
        logger.info("[MAIN] Dry run - not sending email")
        print("\n" + "=" * 60)
        print("GENERATED EMAIL:")
        print("=" * 60)
        print(final_email)
        print("=" * 60)
    else:
        send_email(final_email)

    logger.info("[MAIN] Done!")


if __name__ == "__main__":
    main()
