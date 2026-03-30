#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소셜 미디어 저품질 분석기 - 네이버/유튜브/인스타/스레드/X/틱톡"""

import os
import re
import time
import json
from datetime import datetime
from urllib.parse import quote, unquote_plus

import requests as http_requests
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:
    feedparser = None

app = None
try:
    from flask import Flask, render_template, jsonify, request
    app = Flask(__name__)
except ImportError:
    pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

MAX_SEARCH_TEST = 30  # 검색 노출 테스트 최대 게시글 수


# ═══════════════════════════════════════════════════
# 네이버 블로그
# ═══════════════════════════════════════════════════

def naver_get_blog_info(blog_id):
    info = {"id": blog_id, "name": "", "posts": 0, "platform": "naver"}
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
    return info


def naver_get_posts(blog_id, count=30):
    posts = []
    pages = (count + 29) // 30
    for page in range(1, pages + 1):
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
            break
        if len(posts) >= count:
            break
    return posts[:count]


def naver_check_search(blog_id, title):
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
        search_results.append({"title": p["title"], "exposed": r})
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
    total = exposed + not_exposed

    if total > 0:
        rate = exposed / total * 100
        if rate == 0:
            score += 40
            reasons.append({"text": f"검색 노출 0% ({not_exposed}건 미노출)", "type": "danger"})
        elif rate < 50:
            score += 25
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "warning"})
        elif rate < 80:
            score += 10
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "warning"})
        else:
            reasons.append({"text": f"검색 노출 {rate:.0f}% ({exposed}/{total}건)", "type": "success"})

    if site_indexed is False:
        score += 20
        reasons.append({"text": "site: 검색 미색인", "type": "danger"})
    elif site_indexed is True:
        reasons.append({"text": "site: 검색 색인 확인", "type": "success"})

    if freq["last_post_days_ago"] is not None:
        if freq["last_post_days_ago"] > 90:
            score += 25
            reasons.append({"text": f"마지막 포스팅 {freq['last_post_days_ago']}일 전 (3개월+)", "type": "danger"})
        elif freq["last_post_days_ago"] > 30:
            score += 15
            reasons.append({"text": f"마지막 포스팅 {freq['last_post_days_ago']}일 전", "type": "warning"})
        else:
            reasons.append({"text": f"마지막 포스팅 {freq['last_post_days_ago']}일 전", "type": "success"})

    if freq["recent_gap_days"] and freq["recent_gap_days"].count(0) >= 3:
        score += 15
        reasons.append({"text": f"같은 날 다량 포스팅 감지", "type": "warning"})

    suggestions = []
    if score >= 20:
        if any("미노출" in r["text"] or "노출 0%" in r["text"] for r in reasons):
            suggestions.append("글 제목에 구체적 검색 키워드 포함")
            suggestions.append("본문 1,500자 이상, 직접 촬영 이미지 3장+")
        if any("다량 포스팅" in r["text"] for r in reasons):
            suggestions.append("하루 1-2개씩 나눠서 포스팅")
        suggestions.append("주 2-3회 정기적 포스팅 유지")

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


def make_quality_result(score, reasons, suggestions):
    if score >= 40:
        level, text = "danger", "높음 (저품질 가능성)"
    elif score >= 20:
        level, text = "warning", "보통 (주의 필요)"
    else:
        level, text = "success", "양호"
    return {"score": score, "level": level, "level_text": text, "reasons": reasons, "suggestions": suggestions}


# ═══════════════════════════════════════════════════
# Flask 라우트
# ═══════════════════════════════════════════════════

ANALYZERS = {
    "naver": analyze_naver,
    "youtube": analyze_youtube,
    "instagram": analyze_instagram,
    "x": analyze_x,
    "threads": analyze_threads,
    "tiktok": analyze_tiktok,
}

if app:
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        data = request.get_json()
        platform = data.get("platform", "naver")
        account_id = data.get("id", "").strip()

        if not account_id:
            return jsonify({"error": "ID를 입력해주세요"}), 400

        analyzer = ANALYZERS.get(platform)
        if not analyzer:
            return jsonify({"error": f"지원하지 않는 플랫폼: {platform}"}), 400

        result = analyzer(account_id)
        return jsonify({"result": result, "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M")})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
