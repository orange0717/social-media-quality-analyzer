#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소셜 미디어 저품질 분석기 - 네이버/유튜브/인스타/스레드/X/틱톡"""

import os
import re
import time
import json
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote_plus

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 86400  # 24시간


def cache_get(platform, account_id):
    """캐시에서 결과 조회. 유효하면 dict 반환, 아니면 None."""
    key = hashlib.md5(f"{platform}:{account_id}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("cached_at", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def cache_set(platform, account_id, result, analyzed_at):
    """결과를 캐시에 저장."""
    key = hashlib.md5(f"{platform}:{account_id}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    data = {"result": result, "analyzed_at": analyzed_at, "cached_at": time.time()}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

import requests as http_requests
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:
    feedparser = None

app = None
try:
    from flask import Flask, render_template, jsonify, request, Response
    app = Flask(__name__)
except ImportError:
    pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Naver Search API
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

MAX_SEARCH_TEST = 30  # 동기 API용 (스트리밍은 전체 분석)


# ═══════════════════════════════════════════════════
# 네이버 블로그
# ═══════════════════════════════════════════════════

def naver_get_blog_info(blog_id):
    info = {"id": blog_id, "name": "", "posts": 0, "visitors_today": 0, "visitors_total": 0, "platform": "naver"}
    try:
        url = f"https://blog.naver.com/prologue/PrologueList.naver?blogId={blog_id}"
        resp = http_requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            nick = soup.select_one(".nick")
            if nick:
                info["name"] = nick.get_text(strip=True)
            if not info["name"]:
                title = soup.find("title")
                if title:
                    info["name"] = title.get_text(strip=True).replace(" : 네이버 블로그", "")
    except Exception:
        pass
    try:
        post_url = f"https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}&viewdate=&currentPage=1&categoryNo=0&parentCategoryNo=0&countPerPage=1"
        resp = http_requests.get(post_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            m = re.search(r'"totalCount"\s*:\s*"?(\d+)"?', resp.text)
            if m:
                info["posts"] = int(m.group(1))
    except Exception:
        pass
    # 방문자수 (모바일 페이지에서 추출)
    try:
        mobile_url = f"https://m.blog.naver.com/{blog_id}"
        resp = http_requests.get(mobile_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            m_today = re.search(r'오늘\s*([\d,]+)', resp.text)
            if m_today:
                info["visitors_today"] = int(m_today.group(1).replace(",", ""))
            m_total = re.search(r'전체\s*([\d,]+)', resp.text)
            if m_total:
                info["visitors_total"] = int(m_total.group(1).replace(",", ""))
    except Exception:
        pass
    return info


def naver_get_posts_page(blog_id, page):
    """단일 페이지(30건) fetch"""
    posts = []
    try:
        url = f"https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}&viewdate=&currentPage={page}&categoryNo=0&parentCategoryNo=0&countPerPage=30"
        resp = http_requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            titles = re.findall(r'"title"\s*:\s*"([^"]*)"', resp.text)
            dates = re.findall(r'"addDate"\s*:\s*"([^"]*)"', resp.text)
            log_nos = re.findall(r'"logNo"\s*:\s*"?(\d+)"?', resp.text)
            for i in range(min(len(titles), len(dates))):
                posts.append({
                    "title": unquote_plus(titles[i]),
                    "date": dates[i] if i < len(dates) else "",
                    "id": log_nos[i] if i < len(log_nos) else "",
                })
    except Exception:
        pass
    return posts


def naver_get_posts(blog_id, count=30):
    posts = []
    pages = (count + 29) // 30
    for page in range(1, pages + 1):
        fetched = naver_get_posts_page(blog_id, page)
        posts.extend(fetched)
        if len(fetched) < 30 or len(posts) >= count:
            break
    return posts[:count]


def naver_check_search(blog_id, title):
    """Naver Search API로 검색 노출 확인. 상위 10건/전체 100건 구분 반환."""
    if not title:
        return None
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return _naver_check_search_scrape(blog_id, title)
    try:
        api_url = "https://openapi.naver.com/v1/search/blog.json"
        params = {"query": title[:50].strip(), "display": 100}
        api_headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        resp = http_requests.get(api_url, headers=api_headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for idx, item in enumerate(items):
                link = item.get("bloggerlink", "") + item.get("link", "")
                if blog_id.lower() in link.lower():
                    return {"exposed": True, "rank": idx + 1, "top10": idx < 10}
            return {"exposed": False, "rank": None, "top10": False}
    except Exception:
        pass
    return None


def _normalize_search_result(title, r):
    """naver_check_search 결과를 통일된 형식으로 변환"""
    if r is None:
        return {"title": title, "exposed": None, "rank": None, "top10": False}
    if isinstance(r, dict):
        return {"title": title, "exposed": r.get("exposed"), "rank": r.get("rank"), "top10": r.get("top10", False)}
    # bool (스크래핑 폴백)
    return {"title": title, "exposed": r, "rank": None, "top10": False}


def _naver_check_search_scrape(blog_id, title):
    """폴백: 스크래핑 방식 (API 키 없을 때)"""
    if not title:
        return None
    try:
        q = quote(title[:30].strip())
        resp = http_requests.get(
            f"https://search.naver.com/search.naver?where=blog&query={q}",
            headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            return blog_id.lower() in resp.text.lower()
    except Exception:
        pass
    return None


def naver_check_site_index(blog_id):
    """Naver Search API로 site: 색인 확인"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return _naver_check_site_index_scrape(blog_id)
    try:
        api_url = "https://openapi.naver.com/v1/search/blog.json"
        params = {"query": f"site:blog.naver.com/{blog_id}", "display": 1}
        api_headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        resp = http_requests.get(api_url, headers=api_headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("total", 0) > 0
    except Exception:
        pass
    return None


def _naver_check_site_index_scrape(blog_id):
    """폴백: 스크래핑 방식"""
    try:
        q = quote(f"site:blog.naver.com/{blog_id}")
        resp = http_requests.get(
            f"https://search.naver.com/search.naver?where=blog&query={q}",
            headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            return blog_id.lower() in resp.text.lower()
    except Exception:
        pass
    return None


def analyze_naver(blog_id):
    info = naver_get_blog_info(blog_id)
    posts = naver_get_posts(blog_id, count=MAX_SEARCH_TEST)
    freq = calc_frequency(posts)

    search_results = []
    for p in posts[:MAX_SEARCH_TEST]:
        r = naver_check_search(blog_id, p["title"])
        search_results.append(_normalize_search_result(p["title"], r))
        time.sleep(0.3)

    site_indexed = naver_check_site_index(blog_id)
    quality = assess_naver_quality(info, posts, freq, search_results, site_indexed)

    return {
        "platform": "naver",
        "id": blog_id,
        "info": info,
        "posts": [{"title": p["title"], "date": p["date"]} for p in posts[:10]],
        "freq": freq,
        "search_results": search_results,
        "site_indexed": site_indexed,
        "quality": quality,
        "url": f"https://blog.naver.com/{blog_id}",
    }


def assess_naver_quality(info, posts, freq, search_results, site_indexed):
    score = 0
    reasons = []

    exposed = sum(1 for r in search_results if r["exposed"] is True)
    not_exposed = sum(1 for r in search_results if r["exposed"] is False)
    checked = exposed + not_exposed  # 확인된 건수만 (None 제외)
    top10_count = sum(1 for r in search_results if r.get("top10") is True)

    if checked > 0:
        rate = exposed / checked * 100
        if rate == 0:
            score += 100
            reasons.append({"text": f"검색 노출 0% ({checked}건 중 전체 미노출) - 저품질 확정", "type": "danger"})
        elif rate < 50:
            score += 25
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{checked}건 노출)", "type": "warning"})
        elif rate < 80:
            score += 10
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{checked}건 노출)", "type": "warning"})
        else:
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{checked}건 노출)", "type": "success"})

        # 상위 10건 노출률 (실제 사용자가 보는 영역)
        top10_rate = top10_count / checked * 100
        if top10_rate == 0 and exposed > 0:
            score += 30
            reasons.append({"text": f"상위 노출 0% (검색 결과에 뜨지만 1페이지 밖) - 실질적 저품질", "type": "danger"})
        elif top10_rate < 30:
            score += 15
            reasons.append({"text": f"상위 노출 {top10_rate:.0f}% ({top10_count}/{checked}건 상위 10위 내)", "type": "warning"})
        elif top10_rate < 60:
            score += 5
            reasons.append({"text": f"상위 노출 {top10_rate:.0f}% ({top10_count}/{checked}건 상위 10위 내)", "type": "warning"})
        else:
            reasons.append({"text": f"상위 노출 {top10_rate:.0f}% ({top10_count}/{checked}건 상위 10위 내)", "type": "success"})

    if site_indexed is False:
        score += 20
        reasons.append({"text": "site: 검색 미색인", "type": "danger"})
    elif site_indexed is True:
        reasons.append({"text": "site: 검색 색인 확인", "type": "success"})

    if freq["last_post_days_ago"] is not None:
        reasons.append({"text": f"마지막 포스팅 {freq['last_post_days_ago']}일 전", "type": "success" if freq["last_post_days_ago"] <= 30 else "warning"})

    # 방문자수 분석
    total_posts = info.get("posts", 0)
    visitors_today = info.get("visitors_today", 0)
    visitors_total = info.get("visitors_total", 0)

    # 일 방문자 절대값 평가 (게시글 많은 블로그 기준)
    if total_posts >= 100:
        if visitors_today == 0:
            score += 25
            reasons.append({"text": f"오늘 방문자 0명 (게시글 {total_posts:,}개 블로그)", "type": "danger"})
        elif visitors_today < 30:
            score += 15
            reasons.append({"text": f"오늘 방문자 {visitors_today:,}명 (게시글 {total_posts:,}개 대비 매우 적음)", "type": "danger"})
        elif visitors_today < 100:
            score += 5
            reasons.append({"text": f"오늘 방문자 {visitors_today:,}명", "type": "warning"})
        else:
            reasons.append({"text": f"오늘 방문자 {visitors_today:,}명", "type": "success"})
    elif visitors_today > 0:
        reasons.append({"text": f"오늘 방문자 {visitors_today:,}명", "type": "success" if visitors_today >= 100 else "warning" if visitors_today >= 30 else "danger"})
    elif total_posts > 0:
        score += 15
        reasons.append({"text": "오늘 방문자 0명", "type": "danger"})

    if visitors_total > 0:
        reasons.append({"text": f"누적 방문자 {visitors_total:,}명", "type": "success" if visitors_total >= 100000 else "warning"})

    # 게시글 대비 방문자수 비율 (일 방문자 / 총 게시글)
    if total_posts >= 50:
        visitor_per_post = visitors_today / total_posts if total_posts > 0 else 0
        if visitor_per_post < 0.005:  # 게시글 200개당 방문자 1명 미만
            score += 25
            reasons.append({"text": f"게시글 대비 방문자 극히 적음 (게시글 {total_posts:,}개, 일 방문자 {visitors_today:,}명, 비율 {visitor_per_post:.4f})", "type": "danger"})
        elif visitor_per_post < 0.01:  # 게시글 100개당 방문자 1명 미만
            score += 15
            reasons.append({"text": f"게시글 대비 방문자 매우 적음 (게시글 {total_posts:,}개, 일 방문자 {visitors_today:,}명)", "type": "danger"})
        elif visitor_per_post < 0.05:  # 게시글 100개당 방문자 5명 미만
            score += 10
            reasons.append({"text": f"게시글 대비 방문자 적음 (게시글 {total_posts:,}개, 일 방문자 {visitors_today:,}명)", "type": "warning"})

    # 공유글 비율 분석
    if len(search_results) >= 10:
        share_count = sum(1 for r in search_results if "[공유]" in r.get("title", "") or "공유" == r.get("title", "")[:2])
        share_rate = share_count / len(search_results) * 100
        if share_rate >= 30:
            score += 10
            reasons.append({"text": f"공유글 비율 {share_rate:.0f}% ({share_count}/{len(search_results)}건) - 원본 콘텐츠 부족", "type": "danger"})
        elif share_rate >= 15:
            score += 5
            reasons.append({"text": f"공유글 비율 {share_rate:.0f}% ({share_count}/{len(search_results)}건)", "type": "warning"})

    suggestions = []
    if score >= 20:
        if any("미노출" in r["text"] or "노출 0%" in r["text"] for r in reasons):
            suggestions.append("글 제목에 구체적 검색 키워드 포함")
            suggestions.append("본문 1,500자 이상, 직접 촬영 이미지 3장+")
        if any("방문자" in r["text"] for r in reasons if r["type"] == "danger"):
            suggestions.append("검색 유입 키워드 분석 후 SEO 최적화 필요")
            suggestions.append("제목에 검색량 높은 키워드를 자연스럽게 포함")
            suggestions.append("공유 글 비중을 줄이고 원본 콘텐츠 비율 높이기")

    return make_quality_result(score, reasons, suggestions)


# ═══════════════════════════════════════════════════
# 유튜브
# ═══════════════════════════════════════════════════

def youtube_get_channel_info(channel_input):
    info = {"id": channel_input, "name": "", "subscribers": "", "videos": 0, "platform": "youtube"}
    channel_id = channel_input

    # @handle이나 채널명을 channel_id로 변환 시도
    try:
        if channel_input.startswith("@") or not channel_input.startswith("UC"):
            url = f"https://www.youtube.com/{channel_input if channel_input.startswith('@') else '@' + channel_input}"
            resp = http_requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                cid = re.search(r'"externalId"\s*:\s*"(UC[^"]+)"', resp.text)
                if cid:
                    channel_id = cid.group(1)
                name = re.search(r'"channelMetadataRenderer".*?"title"\s*:\s*"([^"]+)"', resp.text)
                if name:
                    info["name"] = name.group(1)
                subs = re.search(r'"subscriberCountText".*?"simpleText"\s*:\s*"([^"]+)"', resp.text)
                if subs:
                    info["subscribers"] = subs.group(1)
                vids = re.search(r'"videosCountText".*?"runs".*?"text"\s*:\s*"([\d,]+)"', resp.text)
                if vids:
                    info["videos"] = int(vids.group(1).replace(",", ""))
        else:
            url = f"https://www.youtube.com/channel/{channel_id}"
            resp = http_requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                name = re.search(r'"channelMetadataRenderer".*?"title"\s*:\s*"([^"]+)"', resp.text)
                if name:
                    info["name"] = name.group(1)
                subs = re.search(r'"subscriberCountText".*?"simpleText"\s*:\s*"([^"]+)"', resp.text)
                if subs:
                    info["subscribers"] = subs.group(1)
    except Exception:
        pass

    info["channel_id"] = channel_id
    return info


def youtube_get_videos(channel_id):
    videos = []
    if feedparser is None:
        return videos
    try:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:15]:
            videos.append({
                "title": entry.get("title", ""),
                "date": entry.get("published", ""),
                "id": entry.get("yt_videoid", ""),
                "link": entry.get("link", ""),
            })
    except Exception:
        pass
    return videos


def youtube_get_view_count(video_id):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        resp = http_requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            m = re.search(r'"viewCount"\s*:\s*"(\d+)"', resp.text)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def youtube_check_search(channel_name, video_title):
    if not video_title:
        return None
    try:
        q = quote(video_title[:30].strip())
        resp = http_requests.get(
            f"https://www.youtube.com/results?search_query={q}",
            headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            return channel_name.lower() in resp.text.lower() if channel_name else None
    except Exception:
        pass
    return None


def analyze_youtube(channel_input):
    info = youtube_get_channel_info(channel_input)
    channel_id = info.get("channel_id", channel_input)
    videos = youtube_get_videos(channel_id)

    # 조회수 수집 (최근 5개만 - 속도 위해)
    view_counts = []
    for v in videos[:5]:
        if v.get("id"):
            vc = youtube_get_view_count(v["id"])
            v["views"] = vc
            if vc is not None:
                view_counts.append(vc)
            time.sleep(0.3)

    freq = calc_frequency_iso(videos)

    # 검색 노출 테스트
    search_results = []
    for v in videos[:MAX_SEARCH_TEST]:
        r = youtube_check_search(info["name"], v["title"])
        search_results.append({"title": v["title"], "exposed": r})
        time.sleep(0.3)

    quality = assess_youtube_quality(info, videos, freq, view_counts, search_results)

    return {
        "platform": "youtube",
        "id": channel_input,
        "info": info,
        "posts": [{"title": v["title"], "date": v["date"][:10] if v["date"] else "", "views": v.get("views")} for v in videos[:10]],
        "freq": freq,
        "search_results": search_results,
        "quality": quality,
        "url": f"https://www.youtube.com/{channel_input if channel_input.startswith('@') else '@' + channel_input}",
    }


def assess_youtube_quality(info, videos, freq, view_counts, search_results):
    score = 0
    reasons = []

    # 검색 노출
    exposed = sum(1 for r in search_results if r["exposed"] is True)
    not_exposed = sum(1 for r in search_results if r["exposed"] is False)
    total = exposed + not_exposed
    if total > 0:
        rate = exposed / total * 100
        if rate < 30:
            score += 30
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "danger"})
        elif rate < 70:
            score += 15
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "warning"})
        else:
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "success"})

    # 업로드 빈도
    if freq["last_post_days_ago"] is not None:
        if freq["last_post_days_ago"] > 90:
            score += 25
            reasons.append({"text": f"마지막 업로드 {freq['last_post_days_ago']}일 전", "type": "danger"})
        elif freq["last_post_days_ago"] > 30:
            score += 15
            reasons.append({"text": f"마지막 업로드 {freq['last_post_days_ago']}일 전", "type": "warning"})
        else:
            reasons.append({"text": f"마지막 업로드 {freq['last_post_days_ago']}일 전", "type": "success"})

    # 조회수 추이
    if len(view_counts) >= 3:
        avg_views = sum(view_counts) / len(view_counts)
        recent_avg = sum(view_counts[:2]) / 2
        if avg_views > 0 and recent_avg < avg_views * 0.3:
            score += 20
            reasons.append({"text": f"조회수 급감 (평균 {avg_views:.0f} → 최근 {recent_avg:.0f})", "type": "danger"})
        elif avg_views > 0:
            reasons.append({"text": f"평균 조회수 {avg_views:.0f}회", "type": "success"})

    suggestions = []
    if score >= 20:
        suggestions.append("꾸준한 업로드 스케줄 유지 (최소 주 1회)")
        suggestions.append("트렌드 키워드를 제목/태그에 활용")
        if any("조회수" in r["text"] for r in reasons if r["type"] == "danger"):
            suggestions.append("썸네일과 제목을 A/B 테스트하세요")

    return make_quality_result(score, reasons, suggestions)


# ═══════════════════════════════════════════════════
# 인스타그램
# ═══════════════════════════════════════════════════

def analyze_instagram(username):
    username = username.lstrip("@")
    info = {"id": username, "name": username, "posts": 0, "followers": "", "platform": "instagram"}

    try:
        url = f"https://www.instagram.com/{username}/"
        resp = http_requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            m_name = re.search(r'"name"\s*:\s*"([^"]*)"', resp.text)
            if m_name and m_name.group(1):
                info["name"] = m_name.group(1)
            m_desc = re.search(r'"description"\s*:\s*"([^"]*)"', resp.text)
            if m_desc:
                info["description"] = m_desc.group(1)
    except Exception:
        pass

    quality = {
        "score": 0,
        "level": "info",
        "level_text": "제한적 분석",
        "reasons": [
            {"text": "인스타그램은 로그인 없이 상세 데이터 접근 불가", "type": "warning"},
            {"text": "공개 프로필 기본 정보만 확인 가능", "type": "warning"},
        ],
        "suggestions": [
            "Instagram Graph API 연동으로 상세 분석 가능",
            "크리에이터 스튜디오에서 인사이트 직접 확인",
        ],
    }

    return {
        "platform": "instagram",
        "id": username,
        "info": info,
        "posts": [],
        "freq": {"avg_per_week": 0, "avg_per_month": 0, "last_post_days_ago": None, "recent_gap_days": [], "post_dates": []},
        "search_results": [],
        "quality": quality,
        "url": f"https://www.instagram.com/{username}/",
        "limited": True,
    }


# ═══════════════════════════════════════════════════
# X (Twitter)
# ═══════════════════════════════════════════════════

def analyze_x(username):
    username = username.lstrip("@")
    info = {"id": username, "name": username, "platform": "x"}

    try:
        url = f"https://x.com/{username}"
        resp = http_requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code == 200:
            m_name = re.search(r'"name"\s*:\s*"([^"]*)"', resp.text)
            if m_name and m_name.group(1):
                info["name"] = m_name.group(1)
    except Exception:
        pass

    quality = {
        "score": 0,
        "level": "info",
        "level_text": "제한적 분석",
        "reasons": [
            {"text": "X(Twitter)는 로그인 없이 데이터 접근 불가", "type": "warning"},
            {"text": "X API(유료) 연동으로 상세 분석 가능", "type": "warning"},
        ],
        "suggestions": [
            "X Developer API 연동으로 노출/참여도 분석",
            "X Analytics에서 직접 확인",
        ],
    }

    return {
        "platform": "x",
        "id": username,
        "info": info,
        "posts": [],
        "freq": {"avg_per_week": 0, "avg_per_month": 0, "last_post_days_ago": None, "recent_gap_days": [], "post_dates": []},
        "search_results": [],
        "quality": quality,
        "url": f"https://x.com/{username}",
        "limited": True,
    }


# ═══════════════════════════════════════════════════
# 스레드 (Threads)
# ═══════════════════════════════════════════════════

def analyze_threads(username):
    username = username.lstrip("@")
    info = {"id": username, "name": username, "platform": "threads"}

    quality = {
        "score": 0,
        "level": "info",
        "level_text": "제한적 분석",
        "reasons": [
            {"text": "Threads는 공개 API 미제공", "type": "warning"},
            {"text": "서버사이드 크롤링 불가", "type": "warning"},
        ],
        "suggestions": [
            "Threads API 정식 출시 후 연동 예정",
            "Instagram 크리에이터 스튜디오에서 Threads 인사이트 확인",
        ],
    }

    return {
        "platform": "threads",
        "id": username,
        "info": info,
        "posts": [],
        "freq": {"avg_per_week": 0, "avg_per_month": 0, "last_post_days_ago": None, "recent_gap_days": [], "post_dates": []},
        "search_results": [],
        "quality": quality,
        "url": f"https://www.threads.net/@{username}",
        "limited": True,
    }


# ═══════════════════════════════════════════════════
# 틱톡
# ═══════════════════════════════════════════════════

def analyze_tiktok(username):
    username = username.lstrip("@")
    info = {"id": username, "name": username, "platform": "tiktok"}

    try:
        url = f"https://www.tiktok.com/@{username}"
        resp = http_requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            m = re.search(r'"nickname"\s*:\s*"([^"]*)"', resp.text)
            if m and m.group(1):
                info["name"] = m.group(1)
            m_fans = re.search(r'"followerCount"\s*:\s*(\d+)', resp.text)
            if m_fans:
                info["followers"] = int(m_fans.group(1))
            m_vids = re.search(r'"videoCount"\s*:\s*(\d+)', resp.text)
            if m_vids:
                info["videos"] = int(m_vids.group(1))
            m_likes = re.search(r'"heartCount"\s*:\s*(\d+)', resp.text)
            if m_likes:
                info["total_likes"] = int(m_likes.group(1))
    except Exception:
        pass

    has_data = "followers" in info or "videos" in info
    if has_data:
        quality = assess_tiktok_quality(info)
    else:
        quality = {
            "score": 0,
            "level": "info",
            "level_text": "제한적 분석",
            "reasons": [{"text": "틱톡 프로필 데이터 접근 제한", "type": "warning"}],
            "suggestions": ["틱톡 크리에이터 포털에서 직접 확인"],
        }

    return {
        "platform": "tiktok",
        "id": username,
        "info": info,
        "posts": [],
        "freq": {"avg_per_week": 0, "avg_per_month": 0, "last_post_days_ago": None, "recent_gap_days": [], "post_dates": []},
        "search_results": [],
        "quality": quality,
        "url": f"https://www.tiktok.com/@{username}",
        "limited": not has_data,
    }


def assess_tiktok_quality(info):
    score = 0
    reasons = []

    followers = info.get("followers", 0)
    videos = info.get("videos", 0)
    total_likes = info.get("total_likes", 0)

    if followers > 0:
        reasons.append({"text": f"팔로워 {followers:,}명", "type": "success"})
    if videos > 0:
        reasons.append({"text": f"총 영상 {videos:,}개", "type": "success"})
    if total_likes > 0 and videos > 0:
        avg_likes = total_likes / videos
        reasons.append({"text": f"영상당 평균 좋아요 {avg_likes:,.0f}개", "type": "success" if avg_likes > 100 else "warning"})
    if followers > 0 and total_likes > 0:
        engagement = total_likes / followers
        if engagement < 0.5:
            score += 20
            reasons.append({"text": f"참여율 낮음 ({engagement:.1f}x)", "type": "warning"})

    return make_quality_result(score, reasons, [])


# ═══════════════════════════════════════════════════
# 공통 유틸
# ═══════════════════════════════════════════════════

def calc_frequency(posts):
    """네이버식 날짜 (2026. 3. 2.) 파싱"""
    dates = []
    for p in posts:
        nums = re.findall(r'\d+', p.get("date", ""))
        if len(nums) >= 3:
            try:
                dates.append(datetime(int(nums[0]), int(nums[1]), int(nums[2])))
            except (ValueError, IndexError):
                pass
    return _calc_freq_from_dates(dates)


def calc_frequency_iso(posts):
    """ISO 날짜 파싱 (유튜브 RSS 등)"""
    dates = []
    for p in posts:
        ds = p.get("date", "")
        for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%d"]:
            try:
                d = datetime.strptime(ds[:19], fmt[:len(ds[:19])+2].replace("%z",""))
                dates.append(d)
                break
            except ValueError:
                continue
        else:
            nums = re.findall(r'\d+', ds)
            if len(nums) >= 3:
                try:
                    dates.append(datetime(int(nums[0]), int(nums[1]), int(nums[2])))
                except (ValueError, IndexError):
                    pass
    return _calc_freq_from_dates(dates)


def _calc_freq_from_dates(dates):
    if not dates:
        return {"avg_per_week": 0, "avg_per_month": 0, "last_post_days_ago": None, "recent_gap_days": [], "post_dates": []}

    dates.sort(reverse=True)
    last_days = (datetime.now() - dates[0]).days
    gaps = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]

    if len(dates) >= 2:
        span = max((dates[0] - dates[-1]).days, 1)
        avg_w = round(len(dates) / (span / 7), 1)
        avg_m = round(len(dates) / (span / 30), 1)
    else:
        avg_w = avg_m = 0

    return {
        "avg_per_week": avg_w,
        "avg_per_month": avg_m,
        "last_post_days_ago": last_days,
        "recent_gap_days": gaps[:5],
        "post_dates": [d.strftime("%Y-%m-%d") for d in dates],
    }


def extract_keywords(search_results):
    """노출/미노출 게시글 제목에서 유효키워드 추출"""
    STOP_WORDS = {
        "은", "는", "이", "가", "을", "를", "의", "에", "에서", "로", "으로",
        "와", "과", "도", "만", "까지", "부터", "에게", "한테", "께",
        "그", "저", "이", "것", "수", "등", "및", "또", "더", "잘", "못",
        "안", "좀", "꼭", "다", "매우", "정말", "진짜", "너무", "아주",
        "하는", "하기", "하고", "하면", "했다", "하다", "되는", "되다",
        "있는", "있다", "없는", "없다", "위한", "대한", "통한",
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
        "to", "for", "of", "with", "and", "or", "not", "no", "my", "your",
    }

    exposed_words = {}
    not_exposed_words = {}

    for r in search_results:
        title = r.get("title", "")
        words = re.findall(r'[가-힣]{2,}|[a-zA-Z]{3,}|\d{4,}', title)
        words = [w for w in words if w.lower() not in STOP_WORDS]

        if r["exposed"] is True:
            for w in words:
                exposed_words[w] = exposed_words.get(w, 0) + 1
        elif r["exposed"] is False:
            for w in words:
                not_exposed_words[w] = not_exposed_words.get(w, 0) + 1

    # 유효키워드: 노출 게시글에만 등장하거나 노출 비율이 높은 키워드
    effective = []
    ineffective = []

    all_words = set(list(exposed_words.keys()) + list(not_exposed_words.keys()))
    for w in all_words:
        exp = exposed_words.get(w, 0)
        nexp = not_exposed_words.get(w, 0)
        total = exp + nexp
        if total < 2:
            continue
        rate = exp / total
        if rate >= 0.7:
            effective.append({"keyword": w, "exposed": exp, "total": total, "rate": round(rate * 100)})
        elif rate <= 0.3:
            ineffective.append({"keyword": w, "exposed": exp, "total": total, "rate": round(rate * 100)})

    effective.sort(key=lambda x: (-x["total"], -x["rate"]))
    ineffective.sort(key=lambda x: (-x["total"], x["rate"]))

    return {"effective": effective[:20], "ineffective": ineffective[:20]}


def make_quality_result(score, reasons, suggestions):
    if score >= 80:
        level, text = "danger", "저품질 위험도: 확정"
    elif score >= 60:
        level, text = "danger", "저품질 위험도: 높음"
    elif score >= 40:
        level, text = "warning", "저품질 위험도: 주의"
    elif score >= 20:
        level, text = "warning", "저품질 위험도: 낮음"
    else:
        level, text = "success", "저품질 위험도: 없음"
    return {"score": score, "level": level, "level_text": text, "reasons": reasons, "suggestions": suggestions}


# ═══════════════════════════════════════════════════
# Flask 라우트
# ═══════════════════════════════════════════════════

# ═══════════════════════════════════════════════════
# 스트리밍 분석기 (SSE용 generator)
# ═══════════════════════════════════════════════════

def analyze_naver_stream(blog_id):
    yield {"type": "progress", "phase": "info", "current": 0, "total": 0,
           "message": "블로그 정보 수집 중..."}
    info = naver_get_blog_info(blog_id)
    total_posts = info.get("posts", 0)

    if total_posts == 0:
        yield {"type": "result", "data": {
            "platform": "naver", "id": blog_id, "info": info,
            "posts": [], "freq": _calc_freq_from_dates([]),
            "search_results": [], "site_indexed": None,
            "quality": make_quality_result(0, [{"text": "게시글이 없습니다", "type": "warning"}], []),
            "url": f"https://blog.naver.com/{blog_id}",
        }, "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        return

    posts = []
    pages = (total_posts + 29) // 30
    for page in range(1, pages + 1):
        fetched = naver_get_posts_page(blog_id, page)
        posts.extend(fetched)
        yield {"type": "progress", "phase": "fetch_posts",
               "current": len(posts), "total": total_posts,
               "message": f"게시글 목록 수집 중 ({len(posts)}/{total_posts}건)..."}
        if len(fetched) < 30:
            break

    # 실제 수집된 게시글 수로 info 업데이트
    info["posts"] = len(posts)
    freq = calc_frequency(posts)

    total_search = len(posts)
    search_results = []
    search_start = time.time()
    for i, p in enumerate(posts):
        r = naver_check_search(blog_id, p["title"])
        search_results.append(_normalize_search_result(p["title"], r))
        if (i + 1) % 3 == 0 or i + 1 == total_search:
            elapsed = time.time() - search_start
            remaining = (elapsed / (i + 1)) * (total_search - i - 1) if i > 0 else 0
            rem_min = int(remaining // 60)
            rem_sec = int(remaining % 60)
            rem_text = f" (약 {rem_min}분 {rem_sec}초 남음)" if rem_min > 0 else f" (약 {rem_sec}초 남음)" if remaining > 5 else ""
            yield {"type": "progress", "phase": "search_test",
                   "current": i + 1, "total": total_search,
                   "message": f"검색 노출 테스트 중 ({i + 1}/{total_search}건){rem_text}"}
        time.sleep(0.3)

    site_indexed = naver_check_site_index(blog_id)
    quality = assess_naver_quality(info, posts, freq, search_results, site_indexed)
    keywords = extract_keywords(search_results)

    yield {"type": "result", "data": {
        "platform": "naver", "id": blog_id, "info": info,
        "posts": [{"title": p["title"], "date": p["date"]} for p in posts[:10]],
        "freq": freq, "search_results": search_results,
        "site_indexed": site_indexed, "quality": quality,
        "keywords": keywords,
        "url": f"https://blog.naver.com/{blog_id}",
    }, "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def analyze_youtube_stream(channel_input):
    yield {"type": "progress", "phase": "info", "current": 0, "total": 0,
           "message": "채널 정보 수집 중..."}
    info = youtube_get_channel_info(channel_input)
    channel_id = info.get("channel_id", channel_input)

    yield {"type": "progress", "phase": "fetch_posts", "current": 0, "total": 0,
           "message": "최근 영상 목록 수집 중..."}
    videos = youtube_get_videos(channel_id)

    total_videos = len(videos)
    view_counts = []
    for i, v in enumerate(videos):
        if v.get("id"):
            vc = youtube_get_view_count(v["id"])
            v["views"] = vc
            if vc is not None:
                view_counts.append(vc)
            yield {"type": "progress", "phase": "view_count",
                   "current": i + 1, "total": total_videos,
                   "message": f"조회수 수집 중 ({i + 1}/{total_videos}건)..."}
            time.sleep(0.3)

    freq = calc_frequency_iso(videos)

    total_search = len(videos)
    search_results = []
    for i, v in enumerate(videos):
        r = youtube_check_search(info["name"], v["title"])
        search_results.append({"title": v["title"], "exposed": r})
        yield {"type": "progress", "phase": "search_test",
               "current": i + 1, "total": total_search,
               "message": f"검색 노출 테스트 중 ({i + 1}/{total_search}건)..."}
        time.sleep(0.3)

    quality = assess_youtube_quality(info, videos, freq, view_counts, search_results)
    keywords = extract_keywords(search_results)

    yield {"type": "result", "data": {
        "platform": "youtube", "id": channel_input, "info": info,
        "posts": [{"title": v["title"], "date": v["date"][:10] if v["date"] else "", "views": v.get("views")} for v in videos[:10]],
        "freq": freq, "search_results": search_results, "quality": quality,
        "keywords": keywords,
        "url": f"https://www.youtube.com/{channel_input if channel_input.startswith('@') else '@' + channel_input}",
    }, "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _wrap_sync_stream(sync_fn):
    def stream_fn(account_id):
        yield {"type": "progress", "phase": "info", "current": 0, "total": 0,
               "message": "프로필 정보 수집 중..."}
        result = sync_fn(account_id)
        yield {"type": "result", "data": result,
               "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    return stream_fn


def extract_id_from_input(platform, raw_input):
    """URL이 입력되면 ID만 추출"""
    raw_input = raw_input.strip().rstrip("/")
    patterns = {
        "naver": [r'blog\.naver\.com/([^/?#]+)', r'blog\.naver\.com/prologue/.*blogId=([^&]+)'],
        "youtube": [r'youtube\.com/(@[^/?#]+)', r'youtube\.com/channel/([^/?#]+)', r'youtube\.com/c/([^/?#]+)'],
        "instagram": [r'instagram\.com/([^/?#]+)'],
        "threads": [r'threads\.net/@?([^/?#]+)'],
        "x": [r'(?:twitter\.com|x\.com)/([^/?#]+)'],
        "tiktok": [r'tiktok\.com/@?([^/?#]+)'],
    }
    for pattern in patterns.get(platform, []):
        m = re.search(pattern, raw_input)
        if m:
            return m.group(1).lstrip("@") if platform not in ("youtube",) else m.group(1)
    return raw_input.lstrip("@")


ANALYZERS = {
    "naver": analyze_naver,
    "youtube": analyze_youtube,
    "instagram": analyze_instagram,
    "x": analyze_x,
    "threads": analyze_threads,
    "tiktok": analyze_tiktok,
}

STREAM_ANALYZERS = {
    "naver": analyze_naver_stream,
    "youtube": analyze_youtube_stream,
    "instagram": _wrap_sync_stream(analyze_instagram),
    "x": _wrap_sync_stream(analyze_x),
    "threads": _wrap_sync_stream(analyze_threads),
    "tiktok": _wrap_sync_stream(analyze_tiktok),
}

if app:
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        data = request.get_json()
        platform = data.get("platform", "naver")
        raw_id = data.get("id", "").strip()
        account_id = extract_id_from_input(platform, raw_id) if raw_id else ""

        if not account_id:
            return jsonify({"error": "ID를 입력해주세요"}), 400

        analyzer = ANALYZERS.get(platform)
        if not analyzer:
            return jsonify({"error": f"지원하지 않는 플랫폼: {platform}"}), 400

        result = analyzer(account_id)
        return jsonify({"result": result, "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")})

    @app.route("/api/analyze/stream")
    def api_analyze_stream():
        platform = request.args.get("platform", "naver")
        raw_id = request.args.get("id", "").strip()
        account_id = extract_id_from_input(platform, raw_id) if raw_id else ""

        if not account_id:
            def error_gen():
                yield f"data: {json.dumps({'type': 'error', 'message': 'ID를 입력해주세요'}, ensure_ascii=False)}\n\n"
            return Response(error_gen(), mimetype="text/event-stream",
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        analyzer = STREAM_ANALYZERS.get(platform)
        if not analyzer:
            def error_gen():
                yield f"data: {json.dumps({'type': 'error', 'message': f'지원하지 않는 플랫폼: {platform}'}, ensure_ascii=False)}\n\n"
            return Response(error_gen(), mimetype="text/event-stream",
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        # 캐시 확인
        cached = cache_get(platform, account_id)
        if cached:
            def cached_gen():
                result_data = cached["result"]
                result_data["cached"] = True
                yield f"data: {json.dumps({'type': 'result', 'data': result_data, 'analyzed_at': cached['analyzed_at']}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return Response(cached_gen(), mimetype="text/event-stream",
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        def generate():
            last_result = None
            gen = analyzer(account_id)
            try:
                for event in gen:
                    if event.get("type") == "result":
                        last_result = event
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except GeneratorExit:
                gen.close()
                return
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            if last_result:
                cache_set(platform, account_id, last_result["data"], last_result.get("analyzed_at", ""))
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                       headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port, threaded=True)
