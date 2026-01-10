import os
import streamlit as st 
import pandas as pd 
import plotly.express as px 
import plotly.graph_objects as go 
import qrcode
import json
from PIL import Image
from io import BytesIO
from datetime import datetime 
from sqlalchemy import text

# Set headless mode to avoid warning
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"

# --- 数据持久化 (Supabase) ---
def init_db():
    """Initialize database tables if not exist"""
    try:
        conn = st.connection("supabase", type="sql")
        with conn.session as s:
            # Table: groups_data
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS groups_data (
                    group_name TEXT PRIMARY KEY,
                    total_score FLOAT,
                    score_punctuality FLOAT,
                    score_focus FLOAT,
                    score_help FLOAT,
                    score_vitality FLOAT,
                    total_leave_hours FLOAT
                );
            """))
            # Table: logs
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS logs (
                    id SERIAL PRIMARY KEY,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            # Table: approvals
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS approvals (
                    id SERIAL PRIMARY KEY,
                    content TEXT
                );
            """))
            # Table: leave_records
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS leave_records (
                    id SERIAL PRIMARY KEY,
                    group_name TEXT,
                    name TEXT,
                    hours FLOAT
                );
            """))
            s.commit()
    except Exception as e:
        st.error(f"Database initialization failed: {e}")

def load_data():
    init_db()
    conn = st.connection("supabase", type="sql")
    
    # Load Groups Data
    df = conn.query("SELECT * FROM groups_data;", ttl=0)
    
    if df.empty:
        global groups
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
        # Save initial data to DB
        with conn.session as s:
            for _, row in df.iterrows():
                s.execute(text("""
                    INSERT INTO groups_data (group_name, total_score, score_punctuality, score_focus, score_help, score_vitality, total_leave_hours)
                    VALUES (:group_name, :total_score, :score_punctuality, :score_focus, :score_help, :score_vitality, :total_leave_hours)
                """), {
                    "group_name": row["小组"],
                    "total_score": row["总分"],
                    "score_punctuality": row["自强不息(准时)"],
                    "score_focus": row["行胜于言(专注)"],
                    "score_help": row["厚德载物(互助)"],
                    "score_vitality": row["无体育不清华(活力)"],
                    "total_leave_hours": row["总请假时长"]
                })
            s.commit()
    else:
        # Map DB columns to DF columns
        df = df.rename(columns={
            "group_name": "小组",
            "total_score": "总分",
            "score_punctuality": "自强不息(准时)",
            "score_focus": "行胜于言(专注)",
            "score_help": "厚德载物(互助)",
            "score_vitality": "无体育不清华(活力)",
            "total_leave_hours": "总请假时长"
        })
        global groups
        groups = df["小组"].tolist()

    # Load Logs
    logs_df = conn.query("SELECT content FROM logs ORDER BY id DESC;", ttl=0)
    logs = logs_df["content"].tolist() if not logs_df.empty else []

    # Load Approvals
    approvals_df = conn.query("SELECT id, content FROM approvals ORDER BY id;", ttl=0)
    approvals = []
    if not approvals_df.empty:
        for _, row in approvals_df.iterrows():
            item = json.loads(row["content"])
            item["db_id"] = row["id"] # Keep track of DB ID for deletion
            approvals.append(item)

    # Load Leave Records
    leave_df = conn.query("SELECT group_name, name, hours FROM leave_records;", ttl=0)
    leave_records = []
    if not leave_df.empty:
        for _, row in leave_df.iterrows():
            leave_records.append({
                "group": row["group_name"],
                "name": row["name"],
                "hours": row["hours"]
            })

    return df, logs, approvals, leave_records

def save_group_data(group_name, dimension, change, total_change, leave_change=0):
    conn = st.connection("supabase", type="sql")
    col_map = {
        "自强不息(准时)": "score_punctuality",
        "行胜于言(专注)": "score_focus",
        "厚德载物(互助)": "score_help",
        "无体育不清华(活力)": "score_vitality"
    }
    db_col = col_map.get(dimension)
    
    with conn.session as s:
        if db_col:
            s.execute(text(f"""
                UPDATE groups_data 
                SET {db_col} = {db_col} + :change, 
                    total_score = total_score + :total_change
                WHERE group_name = :group_name
            """), {"change": change, "total_change": total_change, "group_name": group_name})
        
        if leave_change > 0:
             s.execute(text("""
                UPDATE groups_data 
                SET total_leave_hours = total_leave_hours + :leave_change
                WHERE group_name = :group_name
            """), {"leave_change": leave_change, "group_name": group_name})
        s.commit()

def add_log(content):
    conn = st.connection("supabase", type="sql")
    with conn.session as s:
        s.execute(text("INSERT INTO logs (content) VALUES (:content)"), {"content": content})
        s.commit()

def add_approval(item):
    conn = st.connection("supabase", type="sql")
    with conn.session as s:
        s.execute(text("INSERT INTO approvals (content) VALUES (:content)"), {"content": json.dumps(item)})
        s.commit()

def delete_approval(db_id):
    conn = st.connection("supabase", type="sql")
    with conn.session as s:
        s.execute(text("DELETE FROM approvals WHERE id = :id"), {"id": db_id})
        s.commit()

def add_leave_record(group, name, hours):
    conn = st.connection("supabase", type="sql")
    with conn.session as s:
        s.execute(text("INSERT INTO leave_records (group_name, name, hours) VALUES (:group, :name, :hours)"), 
                 {"group": group, "name": name, "hours": hours})
        s.commit()

# --- 页面配置 --- 
st.set_page_config(page_title="清华企业家班纪律看板", layout="wide") 

# 清华紫主题色 
TSINGHUA_PURPLE = "#660874" 
st.markdown(f""" 
    <style> 
    .main {{ background-color: #f5f5f5; }} 
    .stHeader {{ color: {TSINGHUA_PURPLE}; }} 
    .stProgress > div > div > div > div {{ background-color: {TSINGHUA_PURPLE}; }} 
    </style> 
    """, unsafe_allow_html=True) 

# --- 模拟数据库 (实际使用建议保存为CSV) --- 
if 'data' not in st.session_state: 
    st.session_state.data, st.session_state.logs, st.session_state.approvals, st.session_state.leave_records = load_data()

# 默认小组密码 (实际应用应从数据库读取)
GROUP_PASSWORDS = {g: "123" for g in groups}

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
        label: st.column_config.NumberColumn(label, min_value=0, step=1, required=True),
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
        for _, row in edited_df.iterrows():
            count = row[label]
            if count > 0:
                group = row["小组"]
                reason = row["备注"]
                change = count * unit
                
                # Update
                idx = st.session_state.data[st.session_state.data["小组"] == group].index[0]
                st.session_state.data.loc[idx, dimension] += change
                st.session_state.data.loc[idx, "总分"] += change
                log_msg = f"{datetime.now().strftime('%H:%M')} | {group} {dimension} {change:+d} | 原因: {reason} ({label}: {count})"
                st.session_state.logs.insert(0, log_msg)
                
                # DB Sync
                save_group_data(group, dimension, change, change)
                add_log(log_msg)
                
                count_updates += 1
        
        if count_updates > 0:
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
        save_group_data(group, dimension, change, change)
        add_log(log_msg)
        
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
        add_approval(item)
        
        st.success("✅ 申请已提交！请通知管理员审核。")
        st.rerun()

@st.dialog("提交请假申请")
def leave_submit_dialog(group_name):
    st.markdown(f"### 📝 {group_name} - 请假登记")
    st.info("总学时：42小时。个人请假超过20% (8.4小时) 将不予结业。")
    
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
        add_approval(item)
        
        st.success("✅ 请假申请已提交！请通知管理员审核。")
        st.rerun()

# --- 侧边栏：角色控制台 --- 
with st.sidebar: 
    st.header("⚙️ 班级控制台") 
    
    # 角色切换
    role = st.radio("当前身份", ["管理员", "小组组长"], horizontal=True)
    st.divider()

    if role == "管理员":
        password = st.text_input("管理员密码", type="password") 
        if password == "THU2024": # 预设密码 
            
            # --- 审核队列 ---
            if st.session_state.approvals:
                st.warning(f"🔔 有 {len(st.session_state.approvals)} 条待审核申请")
                with st.expander("📋 审核队列 (点击处理)", expanded=True):
                    # Iterate copy to modify list safely
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
                                add_leave_record(item['group'], item['name'], item['hours'])
                                save_group_data(item['group'], None, 0, 0, leave_change=item['hours'])
                                add_log(log_msg)
                                delete_approval(item.get("db_id"))
                                
                                st.rerun()
                                
                            if c2.button("❌ 驳回", key=f"rej_{i}"):
                                st.session_state.approvals.pop(i)
                                # DB Sync
                                delete_approval(item.get("db_id"))
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
                                save_group_data(item['group'], item['dimension'], item['change'], item['change'])
                                add_log(log_msg)
                                delete_approval(item.get("db_id"))
                                
                                st.rerun()
                                
                            if c2.button("❌ 驳回", key=f"rej_{i}"):
                                st.session_state.approvals.pop(i)
                                # DB Sync
                                delete_approval(item.get("db_id"))
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
                
                # DB Sync - Need raw SQL for rename or update
                conn = st.connection("supabase", type="sql")
                with conn.session as s:
                    s.execute(text("UPDATE groups_data SET group_name = :new WHERE group_name = :old"), 
                             {"new": new_name, "old": old_name})
                    s.commit()
                add_log(f"{datetime.now().strftime('%H:%M')} | 系统消息: {old_name} 更名为 {new_name}")
                
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
            st.info("请输入密码解锁管理权限") 
            
    else: # 小组组长
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

# --- 主界面 --- 
st.title("💜 清华大学武汉企业家研修二期") 
st.subheader("“自强不息，厚德载物” —— 班级纪律实时统计") 

# 1. 清华马拉松进度条 (Progress Bars) 
st.markdown("### 🏃 清华园马拉松进度 (目标: 500分)") 

# 使用 st.columns(2) 创建两列布局，在移动端会自动堆叠
for i, row in st.session_state.data.iterrows():
    # 每两行数据分一组
    if i % 2 == 0:
        cols = st.columns(2)
    
    col_idx = i % 2
    with cols[col_idx]:
        st.markdown(f"**{row['小组']}**")
        progress = min(row['总分'] / 500, 1.0) # 假设500分为终点 
        st.progress(progress)
        st.caption(f"当前积分: {int(row['总分'])} 分")
        
        # Display leave info
        leave_hours = row['总请假时长']
        if leave_hours > 0:
            st.info(f"📅 请假累计: {leave_hours}h")

st.divider() 

# 2. 核心图表区 
tab1, tab2 = st.tabs(["🕸️ 能量雷达", "🏆 积分排行"])

with tab1:
    # 转换数据为长表以适配 Plotly 
    df_melt = st.session_state.data.melt(id_vars="小组", value_vars=["自强不息(准时)", "行胜于言(专注)", "厚德载物(互助)", "无体育不清华(活力)"]) 
    fig = px.line_polar(df_melt, r="value", theta="variable", color="小组", line_close=True, 
                        color_discrete_sequence=px.colors.qualitative.Prism) 
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5)
    ) 
    st.plotly_chart(fig, use_container_width=True) 
    
with tab2:
    rank_df = st.session_state.data[["小组", "总分"]].sort_values(by="总分", ascending=False) 
    fig_rank = px.bar(rank_df, x="总分", y="小组", orientation='h', 
                      color="总分", color_continuous_scale="Purples") 
    fig_rank.update_layout(showlegend=False) 
    st.plotly_chart(fig_rank, use_container_width=True) 

# 3. 黑榜 (挂科预警) 与 大事记 
st.divider() 

with st.expander("⛰️ 思过崖", expanded=True):
    # 1. Low Score Warning
    low_performers = st.session_state.data[st.session_state.data["总分"] < 80]["小组"].tolist() 
    if low_performers: 
        for group in low_performers: 
            st.error(f"🚨 {group}：学分亮红灯，请及时充能！") 
            
    # 2. Leave Warning (>20% = 8.4h)
    MAX_LEAVE_HOURS = 8.4
    has_leave_warning = False
    
    # Check individual records
    # Aggregate leave by person
    person_leaves = {}
    for record in st.session_state.leave_records:
        key = f"{record['group']}-{record['name']}"
        person_leaves[key] = person_leaves.get(key, 0) + record['hours']
        
    for key, total_hours in person_leaves.items():
        if total_hours > MAX_LEAVE_HOURS:
            st.error(f"🚫 不予结业：{key} (请假 {total_hours}h > 8.4h)")
            has_leave_warning = True
            
    if not low_performers and not has_leave_warning: 
        st.success("🎉 暂无小组挂科，全员优异！") 

with st.expander("📜 班级能量日志", expanded=False):
    for log in st.session_state.logs[:10]: # 显示最近10条
        st.text(log)
