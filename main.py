"""자율학습 출석 관리. 실제 학생 정보는 코드에 포함하지 않습니다."""
import json
import copy
from datetime import date, datetime, timedelta

import streamlit as st

st.set_page_config(page_title="자율학습 출석 관리", page_icon="📋", layout="wide")

DAYS = "월화수목금토일"
STATUS = ["미확인", "출석", "결석", "지각", "조퇴"]
OTHER = ["학원", "귀가", "외출", "미참여", "기타"]


def monday(d):
    return d - timedelta(days=d.weekday())


def slots(d):
    if d < 5:
        return ["1교시", "2교시"]
    if d == 5:
        return ["오전 1교시", "오전 2교시", "오전 3교시", "오후 4교시", "오후 5교시"]
    return ["오후 1교시", "오후 2교시", "오후 3교시"]


def make_week(start, previous=None):
    teachers = {}
    if previous:
        for d in range(7):
            for slot in slots(d):
                teachers[f"{d}|{slot}"] = previous.get("teachers", {}).get(f"{d}|{slot}", "")
    return {"students": {}, "teachers": teachers, "closed": {}}


def key_for(d, slot):
    return f"{d}|{slot}"


def save_student(week, sid, name, classroom, boarding):
    if sid not in week["students"]:
        week["students"][sid] = {"name": name, "classroom": classroom, "boarding": boarding, "plan": {}, "actual": {}, "note": ""}
    else:
        week["students"][sid].update(name=name, classroom=classroom, boarding=boarding)


def sorted_students(week, classroom="전체"):
    items = [(sid, s) for sid, s in week["students"].items() if classroom == "전체" or s["classroom"] == classroom]
    return sorted(items, key=lambda item: (item[1]["classroom"], item[0]))


def label(sid, s):
    return f'{s["classroom"]}반 · {sid} {s["name"]}'


def render_state(plan, actual):
    if plan != "참여":
        return plan
    return actual or "미확인"


def changes(before, after, path=()):
    """Create leaf-level edits so two teachers changing different cells do not overwrite each other."""
    result = []
    for key in set(before) | set(after):
        p = path + (key,)
        if key not in after:
            result.append({"path": p, "delete": True})
        elif key not in before:
            result.append({"path": p, "value": after[key]})
        elif isinstance(before[key], dict) and isinstance(after[key], dict):
            result.extend(changes(before[key], after[key], p))
        elif before[key] != after[key]:
            result.append({"path": p, "value": after[key]})
    return result


def apply_edits(target, edits):
    for edit in edits:
        path = edit["path"]
        if not path or any(not isinstance(part, str) for part in path):
            continue
        node = target
        for part in path[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            if edit.get("delete"):
                node.pop(path[-1], None)
            else:
                node[path[-1]] = edit["value"]


def connect_sheet():
    try:
        sheet_id = st.secrets.get("SPREADSHEET_ID", "")
        account = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    except (FileNotFoundError, KeyError):
        return None
    if not sheet_id or not account:
        return None
    import gspread
    credentials = json.loads(account)
    client = gspread.service_account_from_dict(credentials)
    book = client.open_by_key(sheet_id)
    try:
        return book.worksheet("events")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title="events", rows=1000, cols=3)
        ws.append_row(["기록시각", "변경사항(JSON)"], value_input_option="RAW")
        return ws


try:
    sheet = connect_sheet()
    if sheet is not None:
        all_rows = sheet.get_all_values()
        event_count = max(0, len(all_rows) - 1)
        loaded = {}
        for row in all_rows[1:]:
            if len(row) >= 2 and row[1]:
                apply_edits(loaded, json.loads(row[1]))
        st.session_state.weeks = loaded
    elif "weeks" not in st.session_state:
        st.session_state.weeks = {}
except Exception as exc:
    st.error(f"구글 시트를 읽지 못했습니다. 시트 공유·ID·Secrets 설정을 확인해 주세요. ({type(exc).__name__}: {exc})")
    st.stop()

baseline = copy.deepcopy(st.session_state.weeks)


def sync_and_rerun():
    edits = changes(baseline, st.session_state.weeks)
    if sheet is not None and edits:
        try:
            batches, current = [], []
            for edit in edits:
                trial = current + [edit]
                if current and len(json.dumps(trial, ensure_ascii=False)) > 30000:
                    batches.append(current)
                    current = [edit]
                else:
                    current = trial
            if current:
                batches.append(current)
            stamp = datetime.now().isoformat(timespec="seconds")
            sheet.append_rows([[stamp, json.dumps(batch, ensure_ascii=False)] for batch in batches], value_input_option="RAW")
            st.session_state.last_saved = f"{stamp} · {len(batches)}건 저장"
        except Exception as exc:
            st.session_state.weeks = copy.deepcopy(baseline)
            st.error(f"저장하지 못했습니다. 다시 시도해 주세요. ({type(exc).__name__})")
            st.stop()
    st.rerun()

st.title("자율학습 출석 관리")
st.caption("담임은 주간 계획을 수정하고, 감독교사는 휴대폰에서 담당 날짜·교시만 출석을 확인합니다.")
if sheet is None:
    st.warning("체험 모드: 구글 시트가 연결되지 않았습니다. 입력은 현재 브라우저 세션에만 남습니다.")
else:
    st.success(f"구글 시트 연결됨 · 저장 탭: events · 기록 {event_count}건 · 앱 버전 0.3")
    if st.session_state.get("last_saved"):
        st.caption(f"마지막 저장: {st.session_state.last_saved}")

selected = st.date_input("조회할 주의 날짜", date.today())
start = monday(selected)
week_key = start.isoformat()
weeks = st.session_state.weeks
if week_key not in weeks:
    previous = weeks.get((start - timedelta(days=7)).isoformat())
    weeks[week_key] = make_week(start, previous)
week = weeks[week_key]
st.subheader(f"{start:%Y.%m.%d} ~ {start + timedelta(days=6):%m.%d}")

with st.expander("💾 데이터 백업·복원 (시제품)"):
    st.download_button("전체 주간 기록 JSON 다운로드", json.dumps(weeks, ensure_ascii=False, indent=2).encode("utf-8"), file_name="attendance_backup.json", mime="application/json")
    uploaded = st.file_uploader("기존 백업 복원", type="json")
    if uploaded and st.button("백업 적용", type="primary"):
        try:
            payload = json.load(uploaded)
            if not isinstance(payload, dict) or any(not isinstance(v, dict) or "students" not in v for v in payload.values()):
                raise ValueError("출석 데이터 형식이 아닙니다.")
            st.session_state.weeks = payload
            sync_and_rerun()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            st.error(f"백업을 읽지 못했습니다: {exc}")

teacher_tab, supervisor_tab = st.tabs(["🗓️ 담임 · 주간 편집", "📱 감독교사 · 오늘 출석"])

with teacher_tab:
    st.info("학생·참여 일정은 이 주에만 적용됩니다. 이전 주 명단과 계획을 복사해 시작할 수 있습니다.")
    prev_key = (start - timedelta(days=7)).isoformat()
    if prev_key in weeks and st.button("지난주 학생·참여 계획 복사", help="현재 주의 출석 결과와 감독교사 배정은 유지합니다."):
        prev = weeks[prev_key]
        for sid, old in prev["students"].items():
            if sid not in week["students"]:
                week["students"][sid] = {**old, "plan": dict(old.get("plan", {})), "actual": {}, "note": old.get("note", "")}
        sync_and_rerun()

    with st.expander("학생 추가", expanded=not bool(week["students"])):
        with st.form("add_student", clear_on_submit=True):
            a, b, c, d = st.columns(4)
            sid = a.text_input("학번 (고유번호)")
            name = b.text_input("이름")
            classroom = c.text_input("반", value="1")
            boarding = d.selectbox("구분", ["기숙사", "통학"])
            if st.form_submit_button("학생 추가"):
                sid, name, classroom = sid.strip(), name.strip(), classroom.strip()
                if not sid or not name or not classroom:
                    st.error("학번·이름·반을 입력해 주십시오.")
                elif sid in week["students"]:
                    st.error("이미 등록된 학번입니다.")
                else:
                    save_student(week, sid, name, classroom, boarding)
                    sync_and_rerun()

    classes = ["전체"] + sorted({s["classroom"] for s in week["students"].values()})
    chosen_class = st.selectbox("조회할 반", classes, key=f"class_{week_key}")
    rows = sorted_students(week, chosen_class)
    st.markdown("**한 주 일정** · 셀의 `참여`는 출석 확정이 아니라 참여 예정입니다.")
    if rows:
        header = ["학생"] + [f"{(start + timedelta(days=d)):%m/%d}({DAYS[d]})" for d in range(7)]
        table = []
        for sid, s in rows:
            row = {"학생": label(sid, s)}
            for d in range(7):
                codes = [render_state(s.get("plan", {}).get(key_for(d, sl), "미참여"), s.get("actual", {}).get(key_for(d, sl))) for sl in slots(d)]
                row[header[d + 1]] = " / ".join(codes)
            table.append(row)
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.warning("등록된 학생이 없습니다. 위에서 학생을 추가해 주세요.")

    st.markdown("#### 일정·정보 빠른 수정")
    if rows:
        selected_sid = st.selectbox("학생", [sid for sid, _ in rows], format_func=lambda sid: label(sid, week["students"][sid]), key=f"edit_{week_key}_{chosen_class}")
        student = week["students"][selected_sid]
        with st.form(f"edit_form_{week_key}_{selected_sid}"):
            c1, c2, c3 = st.columns(3)
            new_name = c1.text_input("이름", student["name"])
            new_class = c2.text_input("반", student["classroom"])
            new_boarding = c3.selectbox("기숙/통학", ["기숙사", "통학"], index=0 if student["boarding"] == "기숙사" else 1)
            day_plan = {}
            for d in range(7):
                with st.expander(f"{(start + timedelta(days=d)):%m/%d}({DAYS[d]}) 일정", expanded=d == selected.weekday()):
                    cols = st.columns(2 if d < 5 else 3)
                    for i, sl in enumerate(slots(d)):
                        k = key_for(d, sl)
                        opts = ["참여"] + OTHER
                        current = student.get("plan", {}).get(k, "미참여")
                        day_plan[k] = cols[i % len(cols)].selectbox(sl, opts, index=opts.index(current) if current in opts else opts.index("기타"), key=f"plan_{week_key}_{selected_sid}_{k}")
            note = st.text_input("담임 특이사항", student.get("note", ""))
            if st.form_submit_button("이 학생의 변경사항 저장", type="primary"):
                if new_name.strip() and new_class.strip():
                    student.update(name=new_name.strip(), classroom=new_class.strip(), boarding=new_boarding, note=note.strip())
                    for k, plan in day_plan.items():
                        student["plan"][k] = plan
                        if plan != "참여":
                            student["actual"].pop(k, None)
                    sync_and_rerun()
                else:
                    st.error("이름과 반을 입력해 주세요.")
        with st.expander("학생을 이번 주 명단에서 제거"):
            st.warning("이 주의 해당 학생 계획과 출석 기록이 삭제됩니다.")
            if st.button("이 학생 제거", key=f"remove_{week_key}_{selected_sid}"):
                del week["students"][selected_sid]
                sync_and_rerun()

    st.markdown("#### 감독교사 배정 및 휴업")
    with st.form(f"schedule_{week_key}"):
        teacher_changes = {}
        closed_changes = {}
        for d in range(7):
            st.markdown(f"**{(start + timedelta(days=d)):%m/%d}({DAYS[d]})**")
            closed_changes[str(d)] = st.checkbox("휴업 / 운영하지 않음", value=bool(week.get("closed", {}).get(str(d), False)), key=f"closed_{week_key}_{d}")
            cols = st.columns(2 if d < 5 else 3)
            for i, sl in enumerate(slots(d)):
                k = key_for(d, sl)
                teacher_changes[k] = cols[i % len(cols)].text_input(sl, value=week["teachers"].get(k, ""), key=f"teacher_{week_key}_{k}")
        if st.form_submit_button("감독교사·운영일 저장"):
            week["teachers"].update({k: v.strip() for k, v in teacher_changes.items()})
            week["closed"].update(closed_changes)
            sync_and_rerun()

with supervisor_tab:
    day = st.date_input("출석 확인 날짜", value=selected, key="attendance_day")
    if monday(day) != start:
        st.info("위의 '조회할 주의 날짜'를 이 날짜가 속한 주로 변경해 주세요.")
    else:
        di = day.weekday()
        if week.get("closed", {}).get(str(di), False):
            st.warning("이 날짜는 운영하지 않는 날로 설정되어 있습니다.")
        else:
            sl = st.selectbox("담당 교시", slots(di))
            k = key_for(di, sl)
            st.caption(f"감독교사: {week['teachers'].get(k) or '미배정'}")
            planned = [(sid, s) for sid, s in sorted_students(week) if s.get("plan", {}).get(k) == "참여"]
            if not planned:
                st.info("이 교시에 참여 예정인 학생이 없습니다. 담임 화면에서 일정을 등록해 주세요.")
            else:
                counts = {s: 0 for s in STATUS}
                for _, s in planned:
                    counts[s.get("actual", {}).get(k, "미확인")] = counts.get(s.get("actual", {}).get(k, "미확인"), 0) + 1
                st.markdown(f"**예정 {len(planned)}명 · 출석 {counts['출석']} · 미확인 {counts['미확인']} · 결석 {counts['결석']} · 지각 {counts['지각']} · 조퇴 {counts['조퇴']}**")
                only = st.radio("표시", ["미확인 먼저", "전체", "미확인만"], horizontal=True)
                if only == "미확인 먼저":
                    planned.sort(key=lambda pair: (pair[1].get("actual", {}).get(k, "미확인") != "미확인", pair[1]["classroom"], pair[0]))
                elif only == "미확인만":
                    planned = [(sid, s) for sid, s in planned if s.get("actual", {}).get(k, "미확인") == "미확인"]
                for sid, s in planned:
                    status = s.get("actual", {}).get(k, "미확인")
                    with st.container(border=True):
                        st.markdown(f"**{label(sid, s)}**　 ·　 **{status}**")
                        if s.get("note"):
                            st.caption(f"담임 메모: {s['note']}")
                        buttons = st.columns(4)
                        for col, choice in zip(buttons, STATUS[1:]):
                            if col.button(choice, key=f"mark_{week_key}_{k}_{sid}_{choice}", use_container_width=True, type="primary" if choice == "출석" and status == "미확인" else "secondary"):
                                s["actual"][k] = choice
                                sync_and_rerun()
                        if status != "미확인" and st.button("미확인으로 되돌리기", key=f"reset_{week_key}_{k}_{sid}"):
                            s["actual"].pop(k, None)
                            sync_and_rerun()
            with st.expander("예정에 없던 학생 출석 처리"):
                unplanned = [(sid, s) for sid, s in sorted_students(week) if s.get("plan", {}).get(k) != "참여"]
                if unplanned:
                    extra_sid = st.selectbox("학생 선택", [sid for sid, _ in unplanned], format_func=lambda sid: label(sid, week["students"][sid]))
                    if st.button("참여 예정으로 추가하고 출석 처리"):
                        week["students"][extra_sid]["plan"][k] = "참여"
                        week["students"][extra_sid]["actual"][k] = "출석"
                        sync_and_rerun()
                else:
                    st.caption("추가할 학생이 없습니다.")

st.divider()
st.caption("구글 시트 연결 시 변경할 때마다 저장됩니다. 접근 권한을 제한하고 JSON 백업을 정기적으로 보관해 주세요.")
