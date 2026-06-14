# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""数据模型：公司 / 岗位 / 岗位快照 / 抓取日志"""

import datetime
import os

import flask
from flask_sqlalchemy import SQLAlchemy

import config

app = flask.Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(config.DATA_DIR, "jobs.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Company(db.Model):
    """公司表：同名公司只保留一条记录，跨岗位复用"""
    __tablename__ = "Company"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(128), unique=True, nullable=False, name="公司名称")
    industry = db.Column(db.String(64), nullable=True, name="行业")
    scale = db.Column(db.String(64), nullable=True, name="规模")
    financing_stage = db.Column(db.String(64), nullable=True, name="融资阶段")
    first_seen_at = db.Column(db.DateTime, default=datetime.datetime.now, name="首次发现时间")
    last_seen_at = db.Column(db.DateTime, default=datetime.datetime.now, name="最近发现时间")

    jobs = db.relationship("Job", backref="company", cascade="all, delete-orphan")

    def __repr__(self):
        return "<公司 {}>".format(self.name)


class Job(db.Model):
    """岗位主表：保存岗位的最新快照（增量更新时原地覆盖，历史变化记录在JobSnapshot）"""
    __tablename__ = "Job"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), unique=True, nullable=False, name="站内岗位ID")
    title = db.Column(db.String(128), name="岗位名称")
    company_id = db.Column(db.Integer, db.ForeignKey("Company.id"), nullable=False)

    city = db.Column(db.String(32), name="城市")
    area = db.Column(db.String(64), name="区域")
    work_address = db.Column(db.String(255), nullable=True, name="工作地址")

    salary_min = db.Column(db.Float, nullable=True, name="薪资下限")
    salary_max = db.Column(db.Float, nullable=True, name="薪资上限")
    salary_unit = db.Column(db.String(16), nullable=True, name="薪资单位")
    salary_months = db.Column(db.Integer, nullable=True, name="年终倍薪")

    experience_min = db.Column(db.Integer, nullable=True, name="经验下限")
    experience_max = db.Column(db.Integer, nullable=True, name="经验上限")
    education_req = db.Column(db.String(16), nullable=True, name="学历要求")

    skill_tags = db.Column(db.Text, nullable=True, name="技能标签")  # JSON数组文本
    description = db.Column(db.Text, nullable=True, name="岗位描述")
    recruiter_info = db.Column(db.String(128), nullable=True, name="招聘方信息")

    source_keyword = db.Column(db.String(64), nullable=True, name="命中关键词")
    url = db.Column(db.String(255), nullable=True, name="详情页链接")

    first_seen_at = db.Column(db.DateTime, default=datetime.datetime.now, name="首次抓到时间")
    last_seen_at = db.Column(db.DateTime, default=datetime.datetime.now, name="最近一次出现时间")
    is_active = db.Column(db.Boolean, default=True, name="是否仍在招")

    snapshots = db.relationship("JobSnapshot", backref="job", cascade="all, delete-orphan")

    def __repr__(self):
        return "<岗位 {}@{}>".format(self.title, self.company_id)


class JobSnapshot(db.Model):
    """岗位快照表：每次抓到该岗位时记录一条，用于追踪薪资/在招状态随时间的变化"""
    __tablename__ = "JobSnapshot"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.Integer, db.ForeignKey("Job.id"), nullable=False)

    salary_raw = db.Column(db.String(64), nullable=True, name="薪资原文")
    salary_min = db.Column(db.Float, nullable=True, name="薪资下限")
    salary_max = db.Column(db.Float, nullable=True, name="薪资上限")
    captured_at = db.Column(db.DateTime, default=datetime.datetime.now, name="抓取时间")

    def __repr__(self):
        return "<快照 job={} {}>".format(self.job_id, self.captured_at)


class FilteredJob(db.Model):
    """过滤记录表：保存被过滤规则排除、未正式入库的岗位，便于核对过滤效果"""
    __tablename__ = "FilteredJob"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), nullable=True, name="站内岗位ID")
    title = db.Column(db.String(128), nullable=True, name="岗位名称")
    company_name = db.Column(db.String(128), nullable=True, name="公司名称")
    reason = db.Column(db.String(64), nullable=True, name="过滤原因")
    source_keyword = db.Column(db.String(64), nullable=True, name="命中关键词")
    url = db.Column(db.String(255), nullable=True, name="详情页链接")
    filtered_at = db.Column(db.DateTime, default=datetime.datetime.now, name="过滤时间")

    def __repr__(self):
        return "<已过滤 {}@{} 原因={}>".format(self.title, self.company_name, self.reason)


class ChatSession(db.Model):
    """AI对话会话表：每次新对话创建一个session，支持历史记录"""
    __tablename__ = "ChatSession"

    id = db.Column(db.String(36), primary_key=True)  # UUID
    title = db.Column(db.String(100), nullable=True, name="标题")  # 取第一条消息前40字
    created_at = db.Column(db.DateTime, default=datetime.datetime.now, name="创建时间")
    messages = db.relationship("ChatMessage", backref="session",
                               cascade="all, delete-orphan",
                               order_by="ChatMessage.created_at")


class ChatMessage(db.Model):
    """AI对话消息表：记录每轮用户/助手消息及工具调用"""
    __tablename__ = "ChatMessage"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.String(36), db.ForeignKey("ChatSession.id"), nullable=False)
    role = db.Column(db.String(16), nullable=False, name="角色")  # user / assistant
    content = db.Column(db.Text, nullable=False, name="内容")
    tool_calls_json = db.Column(db.Text, nullable=True, name="工具调用记录")  # JSON数组
    created_at = db.Column(db.DateTime, default=datetime.datetime.now, name="时间")


class CoverageRequest(db.Model):
    """用户申请开通的城市+行业组合，调度器凌晨扫描并排队爬取"""
    __tablename__ = "CoverageRequest"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    city = db.Column(db.String(32), nullable=False, name="城市")
    industry = db.Column(db.String(64), nullable=False, name="行业")
    email = db.Column(db.String(128), nullable=True, name="联系邮箱")
    status = db.Column(db.String(16), default="pending", name="状态")  # pending / crawling / done
    created_at = db.Column(db.DateTime, default=datetime.datetime.now, name="申请时间")
    crawled_at = db.Column(db.DateTime, nullable=True, name="完成时间")

    def __repr__(self):
        return "<CoverageRequest {}·{} {}>".format(self.city, self.industry, self.status)


class CrawlLog(db.Model):
    """抓取日志表：记录每个关键词每次抓取批次的执行情况，便于监控健康状况"""
    __tablename__ = "CrawlLog"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    keyword = db.Column(db.String(64), nullable=True, name="搜索关键词")
    started_at = db.Column(db.DateTime, default=datetime.datetime.now, name="开始时间")
    finished_at = db.Column(db.DateTime, nullable=True, name="结束时间")

    total_found = db.Column(db.Integer, default=0, name="本次发现总数")
    new_count = db.Column(db.Integer, default=0, name="新增数量")
    updated_count = db.Column(db.Integer, default=0, name="更新数量")

    status = db.Column(db.String(16), default="running", name="状态")  # running / success / failed
    error_msg = db.Column(db.String(500), nullable=True, name="错误信息")

    def __repr__(self):
        return "<抓取日志 {} {}>".format(self.keyword, self.status)


if __name__ == "__main__":
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with app.app_context():
        db.create_all()
        print("数据库表创建完成: " + app.config["SQLALCHEMY_DATABASE_URI"])
