import os
import json
from datetime import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
import plotly.express as px
import qrcode
from github import Github, GithubException

# --- Page Configuration ---
# Must be the first Streamlit command
st.set_page_config(page_title="清华企业家班纪律看板", layout="wide", page_icon="💜")

# --- Environment Setup ---
# Set headless mode to avoid warning
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"

# --- Constants & Configuration ---
TSINGHUA_PURPLE = "#660874"
REPO_DB_PATH = "data/database.json"
TARGET_SCORE = 500
LOW_SCORE_THRESHOLD = 80
MAX_LEAVE_HOURS = 8.4  # 20% of 42 hours

# Custom CSS for styling
st.markdown(f"""
    <style>
    .main {{ background-color: #f5f5f5; }}
    .stHeader {{ color: {TSINGHUA_PURPLE}; }}
    .stProgress > div > div > div > div {{ background-color: {TSINGHUA_PURPLE}; }}
    </style>
    """, unsafe_allow_html=True)

# --- GitHub Data Storage Functions ---

def get_github_repo():
    """Get GitHub repository object using secrets."""
    try:
        # Check if secrets are available
        if "github" not in st.secrets:
            st.error("Missing 'github' section in .streamlit/secrets.toml")
            return None
            
        token = st.secrets["github"]["token"]
        g = Github(token)
        repo_name = f"{st.secrets['github']['owner']}/{st.secrets['github']['repo']}"
        return g.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub Connection Failed: {e}")
        return None

def read_file_from_github(repo, file_path):
    """Read file content from GitHub."""
    try:
        branch = st.secrets["github"].get("branch", "main")
        contents = repo.get_contents(file_path, ref=branch)
        return contents.decoded_content.decode("utf-8"), contents.sha
    except GithubException as e:
        if e.status == 404:
            return None, None
        raise e

def write_file_to_github(repo, file_path, content, message, sha=None):
    """Write content to GitHub file."""
    try:
        branch = st.secrets["github"].get("branch", "main")
        if sha:
            repo.update_file(file_path, message, content, sha, branch=branch)
        else:
            repo.create_file(file_path, message, content, branch=branch)
        return True
    except Exception as e:
        st.error(f"GitHub Write Failed: {e}")
        return False

def load_data():
    """Load data from GitHub or initialize default data."""
    repo = get_github_repo()
    if not repo:
        # Fallback for local testing without secrets or connection failure
        st.warning("Running in offline mode (GitHub not connected). Data will not be saved permanently.")
        return create_default_data()

    # Load All Data from Single JSON
    content, _ = read_file_from_github(repo, REPO_DB_PATH)
    
    if content:
        try:
            db = json.loads(content)
            df = pd.DataFrame(db.get("groups", []))
            logs = db.get("logs", [])
            approvals = db.get("approvals", [])
            leave_records = db.get("leave_records", [])
            return df, logs, approvals, leave_records
        except json.JSONDecodeError:
            st.error("Database file is corrupted. Loading default data.")
            return create_default_data()
    else:
        # Initialize if not exists
        st.info("Initializing new database on GitHub...")
        df, logs, approvals, leave_records = create_default_data()
        
        # Save initial to GitHub
        initial_db = {
            "groups": df.to_dict(orient="records"),
            "logs": logs,
            "approvals": approvals,
            "leave_records": leave_records
        }
        write_file_to_github(repo, REPO_DB_PATH, json.dumps(initial_db, ensure_ascii=False, indent=2), "Init database.json")
        return df, logs, approvals, leave_records

def create_default_data():
    """Create default initial data structure."""
    groups = ["一组", "二组", "三组", "四组", "五组", "六组", "七组"]
    df = pd.DataFrame({ 
        "小组": groups, 
        "总分": [100.0] * 7, 
        "自强不息(准时)": [25.0] * 7, 
        "行胜于言(专注)": [25.0] * 7, 
        "厚德载物(互助)": [25.0] * 7, 
        "无体育不清华(活力)": [25.0] * 7,
        "总请假时长": [0.0] * 7
    })
    return df, [], [], []

def save_all_data(reason="Update data"):
    """Save all session state data to GitHub with UI feedback."""
    status = st.status("正在同步数据到云端...", expanded=True)
    try:
        repo = get_github_repo()
        if not repo:
            status.update(label="GitHub 连接失败", state="error")
            return False

        # Prepare DB object
        db_data = {
            "groups": st.session_state.data.to_dict(orient="records"),
            "logs": st.session_state.logs,
            "approvals": st.session_state.approvals,
            "leave_records": st.session_state.leave_records
        }
        
        json_content = json.dumps(db_data, ensure_ascii=False, indent=2)
        
        # Read SHA first (to allow update)
        status.write("正在读取远程数据...")
        _, sha = read_file_from_github(repo, REPO_DB_PATH)
        
        # Write Single File
        status.write("正在写入新数据...")
        success = write_file_to_github(repo, REPO_DB_PATH, json_content, f"Update: {reason}", sha)
        
        if not success:
            status.update(label="保存失败", state="error")
            return False
            
        status.update(label="✅ 同步成功！", state="complete", expanded=False)
        return True
    except Exception as e:
        status.update(label=f"发生错误: {str(e)}", state="error")
        return False

# --- Initialization ---

if 'data' not in st.session_state:
    try:
        st.session_state.data, st.session_state.logs, st.session_state.approvals, st.session_state.leave_records = load_data()
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        st.session_state.data, st.session_state.logs, st.session_state.approvals, st.session_state.leave_records = create_default_data()

# Default Group Passwords (In a real app, these should be secure)
GROUP_PASSWORDS = {g: "123" for g in st.session_state.data["小组"]}

# --- Dialog Functions ---

@st.dialog("批量快速评分", width="large")
def batch_quick_score_dialog(title, dimension, unit, label, default_reason):
    st.markdown(f"### {title}")
    st.markdown(f"**计分规则：{label} × {unit} 分**")
    
    # Prepare data for editor
    df_template = pd.DataFrame({
        "小组": st.session_state.data["小组"].tolist(),
        label: [0] * len(st.session_state.data),
        "备注": [default_reason] * len(st.session_state.data)
    })
    
    column_config = {
        "小组": st.column_config.TextColumn("小组", disabled=True),
        label: st.column_config.NumberColumn(label, min_value=0, step=1),
        "备注": st.column_config.TextColumn("备注")
    }
    
    edited_df = st.data_editor(
        df_template,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        key=f"editor_{title}"
    )
    
    if st.button("确认提交", key=f"btn_{title}"):
        count_updates = 0
        updates_info = [] 
        
        # Calculate changes in memory first
        for _, row in edited_df.iterrows():
            count = row[label]
            if count > 0:
                group = row["小组"]
                reason = row["备注"]
                change = count * unit
                
                # Update Session State Data
                idx = st.session_state.data[st.session_state.data["小组"] == group].index[0]
                st.session_state.data.loc[idx, dimension] += change
                st.session_state.data.loc[idx, "总分"] += change
                
                # Prepare Log
                log_msg = f"{datetime.now().strftime('%H:%M')} | {group} {dimension} {change:+d} | 原因: {reason} ({label}: {count})"
                updates_info.append(log_msg)
                count_updates += 1
        
        if count_updates > 0:
            # Batch Insert Logs (reverse order to keep latest first in list)
            for msg in reversed(updates_info):
                st.session_state.logs.insert(0, msg)
                
            # Single DB Sync
            if save_all_data(f"Batch update: {title}"):
                st.success(f"成功更新 {count_updates} 个小组的分数！")
                st.rerun()
        else:
            st.warning("未检测到有效变动（数量均为0）")

@st.dialog("违纪扣分")
def single_quick_score_dialog(dimension, unit, label, default_reason):
    st.markdown(f"**当前维度：{dimension}**")
    st.markdown(f"**规则：每{label} {unit:+d} 分**")
    
    group = st.selectbox("选择小组", st.session_state.data["小组"].tolist())
    count = st.number_input(f"输入{label}", min_value=1, value=1, step=1)
    reason = st.text_input("备注", value=default_reason)
    
    if st.button("确认提交"):
        change = count * unit
        idx = st.session_state.data[st.session_state.data["小组"] == group].index[0]
        st.session_state.data.loc[idx, dimension] += change
        st.session_state.data.loc[idx, "总分"] += change
        log_msg = f"{datetime.now().strftime('%H:%M')} | {group} {dimension} {change:+d} | 原因: {reason} ({label}: {count})"
        st.session_state.logs.insert(0, log_msg)
        
        # DB Sync
        save_all_data(f"Update score: {group}")
        
        st.success("扣分成功！")
        st.rerun()

@st.dialog("提交加分/扣分申请")
def leader_quick_submit_dialog(group_name, dimension, unit, label, default_reason):
    st.markdown(f"### 📝 {group_name} - {label}登记")
    st.markdown(f"**规则：每{label} {unit:+d} 分**")
    
    count = st.number_input(f"输入{label}", min_value=1, value=1, step=1)
    reason = st.text_input("备注说明", value=default_reason)
    
    if st.button("提交审核"):
        change = count * unit
        item = {
            "timestamp": datetime.now().strftime('%H:%M'),
            "group": group_name,
            "dimension": dimension,
            "change": change,
            "reason": f"{reason} ({label}: {count})",
            "status": "pending"
        }
        # Add to approvals
        st.session_state.approvals.append(item)
        
        # DB Sync
        save_all_data(f"New approval: {group_name}")
        
        st.success("✅ 申请已提交！请通知管理员审核。")
        st.rerun()

@st.dialog("提交请假申请")
def leave_submit_dialog(group_name):
    st.markdown(f"### 📝 {group_name} - 请假登记")
    st.info(f"总学时：42小时。个人请假超过20% ({MAX_LEAVE_HOURS}小时) 将不予结业。")
    
    name = st.text_input("学员姓名")
    hours = st.number_input("请假时长 (小时)", min_value=0.5, step=0.5)
    reason = st.text_input("请假原因", placeholder="例如：公司紧急会议")
    
    if st.button("提交请假"):
        if not name:
            st.error("请输入姓名")
            return
        
        item = {
            "timestamp": datetime.now().strftime('%H:%M'),
            "type": "leave",
            "group": group_name,
            "name": name,
            "hours": hours,
            "reason": reason,
            "status": "pending"
        }
        # Add to approvals
        st.session_state.approvals.append(item)
        
        # DB Sync
        save_all_data(f"New leave: {group_name}")
        
        st.success("✅ 请假申请已提交！请通知管理员审核。")
        st.rerun()

# --- Sidebar: Role Control ---
with st.sidebar:
    st.header("⚙️ 班级控制台")
    
    # Role Switcher
    role = st.radio("当前身份", ["管理员", "小组组长"], horizontal=True)
    st.divider()

    if role == "管理员":
        password = st.text_input("管理员密码", type="password") 
        if password == "THU2024": # Default Admin Password
            
            # --- Approval Queue ---
            if st.session_state.approvals:
                st.warning(f"🔔 有 {len(st.session_state.approvals)} 条待审核申请")
                with st.expander("📋 审核队列 (点击处理)", expanded=True):
                    # Iterate over a copy to safely modify the list
                    for i, item in enumerate(list(st.session_state.approvals)):
                        st.markdown(f"**{item['group']}**")
                        
                        if item.get("type") == "leave":
                            st.warning(f"📄 请假申请 | {item['name']} | {item['hours']}小时")
                            st.text(f"原因: {item['reason']}")
                            
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 批准", key=f"app_{i}"):
                                # Record leave
                                st.session_state.leave_records.append({
                                    "group": item['group'],
                                    "name": item['name'],
                                    "hours": item['hours']
                                })
                                # Update group total leave hours
                                idx = st.session_state.data[st.session_state.data["小组"] == item['group']].index[0]
                                st.session_state.data.loc[idx, "总请假时长"] += item['hours']
                                
                                log_msg = f"{datetime.now().strftime('%H:%M')} | [请假批准] {item['group']}-{item['name']} 请假 {item['hours']}小时"
                                st.session_state.logs.insert(0, log_msg)
                                st.session_state.approvals.pop(i)
                                
                                # DB Sync
                                save_all_data(f"Approve leave: {item['name']}")
                                st.rerun()
                                
                            if c2.button("❌ 驳回", key=f"rej_{i}"):
                                st.session_state.approvals.pop(i)
                                # DB Sync
                                save_all_data(f"Reject leave: {item['name']}")
                                st.rerun()
                                
                        else:
                            # Normal score approval
                            st.caption(f"{item['dimension']} | {item['change']:+d}分 | {item['timestamp']}")
                            st.text(f"原因: {item['reason']}")
                            
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 通过", key=f"app_{i}"):
                                # Apply change
                                idx = st.session_state.data[st.session_state.data["小组"] == item['group']].index[0]
                                st.session_state.data.loc[idx, item['dimension']] += item['change']
                                st.session_state.data.loc[idx, "总分"] += item['change']
                                log_msg = f"{datetime.now().strftime('%H:%M')} | [审核通过] {item['group']} {item['dimension']} {item['change']:+d} | 原因: {item['reason']}"
                                st.session_state.logs.insert(0, log_msg)
                                st.session_state.approvals.pop(i)
                                
                                # DB Sync
                                save_all_data(f"Approve score: {item['group']}")
                                st.rerun()
                                
                            if c2.button("❌ 驳回", key=f"rej_{i}"):
                                st.session_state.approvals.pop(i)
                                # DB Sync
                                save_all_data(f"Reject score: {item['group']}")
                                st.rerun()
                        st.divider()
            else:
                st.success("✨ 所有申请已处理完毕")
            
            st.divider()

            st.subheader("快捷评分")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("⏱️ 迟到扣分", use_container_width=True):
                    batch_quick_score_dialog("迟到扣分", "自强不息(准时)", -5, "迟到人数", "迟到")
                if st.button("🤝 互助加分", use_container_width=True):
                    batch_quick_score_dialog("互助加分", "厚德载物(互助)", 5, "表扬人次", "课后整洁/助人")
            with col2:
                if st.button("📵 违纪扣分", use_container_width=True):
                    single_quick_score_dialog("行胜于言(专注)", -10, "违纪次数", "课堂违纪")
                if st.button("🏃 活力加分", use_container_width=True):
                    batch_quick_score_dialog("活力加分", "无体育不清华(活力)", 5, "积极人次", "晨跑/课间操")
                    
            st.divider()
            st.subheader("小组管理")
            with st.expander("📝 修改小组名称"):
                old_name = st.selectbox("选择要修改的小组", st.session_state.data["小组"].tolist())
                new_name = st.text_input("输入新名称")
                
                if st.button("确认改名"):
                    if not new_name.strip():
                        st.error("名称不能为空")
                    elif new_name in st.session_state.data["小组"].values:
                        st.error("该小组名称已存在！")
                    else:
                        idx = st.session_state.data[st.session_state.data["小组"] == old_name].index[0]
                        st.session_state.data.at[idx, "小组"] = new_name
                        st.session_state.logs.insert(0, f"{datetime.now().strftime('%H:%M')} | 系统消息: {old_name} 更名为 {new_name}")
                        
                        # DB Sync
                        if save_all_data(f"Rename group: {old_name} -> {new_name}"):
                            st.success("改名成功！")
                            st.rerun()
            
            st.divider()
            with st.expander("📲 生成分享二维码"):
                qr_url = st.text_input("输入部署后的网址", placeholder="https://tsinghuadashboard.streamlit.app")
                if qr_url:
                    qr = qrcode.QRCode(version=1, box_size=10, border=5)
                    qr.add_data(qr_url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    # Convert to bytes
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    byte_im = buf.getvalue()
                    
                    st.image(byte_im, caption="扫码访问看板", width=200)
                    st.download_button(
                        label="⬇️ 下载二维码",
                        data=byte_im,
                        file_name="dashboard_qr.png",
                        mime="image/png"
                    )
        else:
            if password:
                st.error("密码错误")
            else:
                st.info("请输入密码解锁管理权限")
            
    else: # Group Leader
        st.subheader("组长工作台")
        selected_group = st.selectbox("选择你的小组", st.session_state.data["小组"])
        gp_pw = st.text_input("小组密码", type="password", help="默认密码为 123")
        
        if gp_pw == GROUP_PASSWORDS.get(selected_group, ""):
            st.success(f"✅ 已登录: {selected_group}")
            
            # Show current score
            group_data = st.session_state.data[st.session_state.data["小组"] == selected_group].iloc[0]
            st.metric("当前总分", f"{int(group_data['总分'])} 分")
            
            st.markdown("### 提交申请")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("⏱️ 登记迟到", use_container_width=True):
                    leader_quick_submit_dialog(selected_group, "自强不息(准时)", -5, "迟到人数", "组员迟到")
                if st.button("🏃 登记活力", use_container_width=True):
                    leader_quick_submit_dialog(selected_group, "无体育不清华(活力)", 5, "积极人次", "晨跑/课间操")
            with c2:
                if st.button("🤝 登记互助", use_container_width=True):
                    leader_quick_submit_dialog(selected_group, "厚德载物(互助)", 5, "表扬人次", "课后整洁/助人")
                if st.button("📄 登记请假", use_container_width=True):
                    leave_submit_dialog(selected_group)
                
            st.info("💡 提交后需等待管理员审核生效")
        elif gp_pw:
            st.error("❌ 密码错误")

# --- Main Dashboard Display ---
st.title("💜 清华大学武汉企业家研修二期")
st.subheader("“自强不息，厚德载物” —— 班级纪律实时统计")

# 1. Marathon Progress
st.markdown(f"### 🏃 清华园马拉松进度 (目标: {TARGET_SCORE}分)")

# Use st.columns(2) for responsive grid
for i, row in st.session_state.data.iterrows():
    if i % 2 == 0:
        cols = st.columns(2)
    
    col_idx = i % 2
    with cols[col_idx]:
        st.markdown(f"**{row['小组']}**")
        progress = min(row['总分'] / TARGET_SCORE, 1.0)
        st.progress(progress)
        st.caption(f"当前积分: {int(row['总分'])} 分")
        
        # Display leave info
        leave_hours = row['总请假时长']
        if leave_hours > 0:
            st.info(f"📅 请假累计: {leave_hours}h")

st.divider()

# 2. Charts
tab1, tab2 = st.tabs(["🕸️ 能量雷达", "🏆 积分排行"])

with tab1:
    # Melt data for Radar Chart
    df_melt = st.session_state.data.melt(
        id_vars="小组", 
        value_vars=["自强不息(准时)", "行胜于言(专注)", "厚德载物(互助)", "无体育不清华(活力)"]
    )
    fig = px.line_polar(
        df_melt, r="value", theta="variable", color="小组", line_close=True,
        color_discrete_sequence=px.colors.qualitative.Prism
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5)
    )
    st.plotly_chart(fig, use_container_width=True)
    
with tab2:
    rank_df = st.session_state.data[["小组", "总分"]].sort_values(by="总分", ascending=False)
    fig_rank = px.bar(
        rank_df, x="总分", y="小组", orientation='h',
        color="总分", color_continuous_scale="Purples"
    )
    fig_rank.update_layout(showlegend=False)
    st.plotly_chart(fig_rank, use_container_width=True)

# 3. Alerts and Logs
st.divider()

with st.expander("⛰️ 思过崖 (预警区)", expanded=True):
    # 1. Low Score Warning
    low_performers = st.session_state.data[st.session_state.data["总分"] < LOW_SCORE_THRESHOLD]["小组"].tolist()
    if low_performers:
        for group in low_performers:
            st.error(f"🚨 {group}：学分亮红灯 (<{LOW_SCORE_THRESHOLD}分)，请及时充能！")
            
    # 2. Leave Warning
    has_leave_warning = False
    
    # Aggregate leave by person (names can be duplicated across groups, so key by group+name)
    person_leaves = {}
    for record in st.session_state.leave_records:
        key = f"{record['group']}-{record['name']}"
        person_leaves[key] = person_leaves.get(key, 0) + record['hours']
        
    for key, total_hours in person_leaves.items():
        if total_hours > MAX_LEAVE_HOURS:
            st.error(f"🚫 不予结业：{key} (请假 {total_hours}h > {MAX_LEAVE_HOURS}h)")
            has_leave_warning = True
            
    if not low_performers and not has_leave_warning:
        st.success("🎉 暂无小组挂科，全员优异！")

with st.expander("📜 班级能量日志", expanded=False):
    if st.session_state.logs:
        for log in st.session_state.logs[:10]: # Show last 10
            st.text(log)
    else:
        st.text("暂无记录")
