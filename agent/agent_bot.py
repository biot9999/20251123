#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理机器人（统一通知 + 纯二维码 + 北京时间显示 + 10分钟有效 + 取消订单修复版）
特性:
- 固定地址 + 4 位识别金额自动到账（唯一识别码写入金额小数部分）
- 商品/价格管理、利润提现、统计报表
- 充值/购买/提现群内通知统一使用 HEADQUARTERS_NOTIFY_CHAT_ID
- 充值界面：点击金额后只发送 1 条消息（纯二维码图片 + caption 文案 + 按钮）
- 有效期统一为 10 分钟；caption 中以北京时间显示“有效期至”；超时自动标记 expired
- 二维码内容仅为纯地址（不含 tron: 前缀和 amount 参数），提升钱包兼容性
- 取消订单修复：支持删除原二维码消息或编辑其 caption（通过 RECHARGE_DELETE_ON_CANCEL 环境变量控制）
"""

import os
import sys
import logging
import traceback
import zipfile
import time
import random
import requests
import threading
import re
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pymongo import MongoClient
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
from bson import ObjectId
from html import escape as html_escape
from pathlib import Path
from io import BytesIO
from typing import Union
# 二维码与图片
try:
    import qrcode
    from PIL import Image
except Exception as _qr_import_err:
    qrcode = None
    Image = None
    print(f"⚠️ 二维码依赖未就绪(qrcode/Pillow)，将回退纯文本: {_qr_import_err}")

# ================= 环境变量加载（支持 --env / ENV_FILE / 默认 .env） =================
def _resolve_env_file(argv: list) -> Path:
    env_file_cli = None
    for i, a in enumerate(argv):
        if a == "--env" and i + 1 < len(argv):
            env_file_cli = argv[i + 1]
            break
        if a.startswith("--env="):
            env_file_cli = a.split("=", 1)[1].strip()
            break
    env_file_env = os.getenv("ENV_FILE")
    filename = env_file_cli or env_file_env or ".env"
    p = Path(__file__).parent / filename
    return p

try:
    from dotenv import load_dotenv
    env_path = _resolve_env_file(sys.argv)
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已加载环境文件: {env_path}")
    else:
        print(f"ℹ️ 未找到环境文件 {env_path}，使用系统环境变量")
except Exception as e:
    print(f"⚠️ 环境文件加载失败: {e}")

# ================= 日志配置 =================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("agent_bot")

# 通知群 / 频道
# ✅ 代理自己的通知群（订单、充值、提现通知发这里）
AGENT_NOTIFY_CHAT_ID = os.getenv("AGENT_NOTIFY_CHAT_ID")

# ✅ 总部通知群（代理用来监听总部补货等通知）
HEADQUARTERS_NOTIFY_CHAT_ID = os.getenv("HQ_NOTIFY_CHAT_ID") or os.getenv("HEADQUARTERS_NOTIFY_CHAT_ID")

# ✅ 代理补货通知群（补货通知转发到这里，如未设置则回退到AGENT_NOTIFY_CHAT_ID）
AGENT_RESTOCK_NOTIFY_CHAT_ID = os.getenv("AGENT_RESTOCK_NOTIFY_CHAT_ID")

# ✅ 统一协议号分类配置
AGENT_PROTOCOL_CATEGORY_UNIFIED = os.getenv("AGENT_PROTOCOL_CATEGORY_UNIFIED", "🔥二次协议号（session+json）")
AGENT_PROTOCOL_CATEGORY_ALIASES = os.getenv("AGENT_PROTOCOL_CATEGORY_ALIASES", "协议号,未分类,,🔥二手TG协议号（session+json）,二手TG协议号（session+json）,二次协议号（session+json）")

# ================= 国际化配置 =================
DEFAULT_LANGUAGE = "zh"

I18N = {
    "zh": {
        "common": {
            "back_main": "🏠 主菜单",
            "back": "🔙 返回",
            "not_set": "未设置",
            "back_to_main": "🏠 返回主菜单",
            "refresh": "🔄 刷新",
            "cancel": "🔙 取消",
            "prev_page": "⬅️ 上一页",
            "next_page": "➡️ 下一页",
            "init_failed": "初始化失败，请稍后重试",
            "latest_state": "界面已是最新状态",
            "refresh_failed": "刷新失败，请重试",
            "interface_latest": "界面已是最新",
            "operation_exception": "操作异常",
            "no_permission": "无权限",
            "cancelled": "已取消",
            "unit": "个"
        },
        "start": {
            "welcome": "🎉 欢迎使用 {agent_name}！",
            "user_info": "👤 用户信息",
            "user_id": "• ID: {uid}",
            "username": "• 用户名: @{username}",
            "nickname": "• 昵称: {nickname}",
            "select_function": "请选择功能："
        },
        "main_menu": {
            "title": "🏠 主菜单",
            "current_time": "当前时间: {time}"
        },
        "btn": {
            "products": "🛍️ 商品中心",
            "profile": "👤 个人中心",
            "recharge": "💰 充值余额",
            "orders": "📊 订单历史",
            "support": "📞 联系客服",
            "help": "❓ 使用帮助",
            "price_management": "💰 价格管理",
            "system_reports": "📊 系统报表",
            "profit_center": "💸 利润提现",
            "language": "🌐 语言 / Language",
            "back_main": "🏠 主菜单",
            "back_to_list": "🔙 返回列表",
            "back_to_management": "🔙 返回管理",
            "back_to_edit": "🔙 返回编辑"
        },
        "lang": {
            "menu_title": "🌐 语言选择 / Language Selection",
            "zh_label": "🇨🇳 中文",
            "en_label": "🇬🇧 English",
            "set_ok": "✅ 语言已切换"
        },
        "products": {
            "center": "🛍️ 商品中心",
            "view": "🧾 查看商品",
            "categories": {
                "title": "🛒 商品分类 - 请选择所需商品：",
                "search_tip": "❗快速查找商品，输入区号查找（例：+54）",
                "first_purchase_tip": "❗️首次购买请先少量测试，避免纠纷！",
                "inactive_tip": "❗️长期未使用账户可能会出现问题，联系客服处理。",
                "no_categories": "❌ 暂无可用商品分类"
            },
            "not_exist": "❌ 商品不存在",
            "back_to_list": "🔙 返回商品列表",
            "price_not_set": "❌ 商品价格未设置",
            "buy": "✅ 购买",
            "confirm_purchase": "✅ 确认购买",
            "continue_shopping": "🛍️ 继续购买",
            "purchase_success": "✅ 购买成功！",
            "purchase_failed": "❌ 购买失败: {res}",
            "no_products_wait": "暂无商品耐心等待",
            "insufficient_stock": "❌ 库存不足（当前 {stock}）",
            "no_products_to_manage": "❌ 暂无商品可管理",
            "cannot_find": "❌ 无法找到商品信息",
            "no_longer_exists": "❌ 商品已不存在",
            "file_not_found": "⚠️ 未找到原始商品文件，正在尝试重新获取...",
            "purchasing": "🛒 购买商品",
            "out_of_stock": "⚠️ 商品缺货",
            "purchase_status": "✅您正在购买：",
            "price_label": "💰 价格: {price:.2f} USDT",
            "stock_label": "📦 库存: {stock}个",
            "purchase_warning": "❗未使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！",
            "country_list": "🌍 {title}商品列表 ({codes_display})",
            "country_product": "{name} | {price}U | [{stock}个]"
        },
        "orders": {
            "title": "📊 订单历史",
            "purchase_records": "📦 购买记录",
            "no_records": "暂无购买记录",
            "cancel_order": "❌ 取消订单",
            "not_exist": "❌ 订单不存在或无权访问",
            "details": "📋 订单详情",
            "load_failed": "❌ 加载订单详情失败",
            "overview": "📊 记录概览",
            "total_orders": "• 总订单数：{total}",
            "current_page": "• 当前页显示：{count}",
            "recent_update": "• 最近更新：{time}",
            "operation_guide": "💡 操作说明",
            "operation_tip": "点击下面按钮查看订单详情或重新下载商品"
        },
        "recharge": {
            "title": "💰 充值余额",
            "balance_recharge": "💰 余额充值",
            "records": "📜 充值记录",
            "recent_records_empty": "📜 最近充值记录\n\n暂无记录",
            "recent_records": "📜 最近充值记录（最新优先）",
            "back_to_recharge": "🔙 返回充值",
            "exceed_balance": "❌ 超出可提现余额 {balance:.2f}，请重新输入",
            "insufficient_balance": "❌ 余额不足，需: {total_cost:.2f}U 当前: {bal:.2f}U",
            "amount_generated": "已生成识别金额，请按应付金额转账"
        },
        "profit": {
            "center": "💸 利润中心",
            "apply_withdrawal": "📝 申请提现",
            "application_records": "📋 申请记录",
            "no_withdrawable": "⚠️ 当前无可提现利润",
            "back_to_center": "💸 返回利润中心",
            "budget": "📊 利润预算",
            "calculator": "📊 利润计算器 - {name}\n总部: {op}U（实时价格）",
            "withdrawal_apply": "📝 申请提现",
            "withdrawal_records_empty": "📋 提现记录\n\n暂无申请",
            "withdrawal_records": "📋 提现记录（最新优先）",
            "withdrawal_success": "✅ 提现申请成功\n金额：{amt:.2f} USDT\n地址：{address}\n状态：待审核",
            "amount_recorded": "✅ 金额已记录：{amt:.2f} USDT\n请发送收款地址（TRON 或 ERC20）"
        },
        "price": {
            "management": "💰 价格管理（第{page}页）",
            "config_not_exist": "❌ 代理价格配置不存在",
            "invalid_price": "❌ 请输入有效的价格数字",
            "below_hq_price": "❌ 代理价格不能低于总部价格 {op} USDT",
            "set_rate": "设置 {rate}%({new_agent_price})",
            "update_success": "价格更新成功！加价 {new_markup:.2f}U，利润率 {profit_rate:.1f}%（基于当前总部价 {op}U）",
            "no_change": "无变化",
            "below_hq_error": "代理价格不能低于总部价格 {op} USDT（当前总部价），您输入的 {new_agent_price} USDT 低于总部价",
            "product_not_exist": "原始商品不存在"
        },
        "reports": {
            "center": "📊 系统报表中心",
            "sales": "📈 销售报表（{days}天）",
            "sales_30d": "📈 销售报表(30天)",
            "user_report": "👥 用户报表",
            "user_stats": "👥 用户统计报表",
            "product_report": "📦 商品报表",
            "product_stats": "📦 商品统计报表",
            "financial": "💰 财务报表（{days}天）",
            "financial_30d": "💰 财务报表(30天)",
            "overview": "📊 系统概览报表(30天)",
            "overview_btn": "📊 综合概览",
            "refresh": "🔄 刷新数据",
            "back_to_reports": "🔙 返回报表",
            "7days": "📅 7天",
            "30days": "📅 30天",
            "90days": "📅 90天"
        },
        "user": {
            "profile": "👤 个人中心",
            "contact": "👤 联系用户",
            "info_not_exist": "❌ 用户信息不存在",
            "admin_reloaded": "✅ 管理员列表已重新加载\n\n当前管理员用户ID:\n{admin_list}",
            "admin_reload_no_config": "⚠️ 管理员列表已重新加载，但当前无管理员配置"
        },
        "support": {
            "title": "📞 联系客服",
            "contact": "💬 联系客服",
            "description": "📞 客服 {display}\n请描述问题 + 用户ID/订单号，便于快速处理。",
            "file_send_failed": "❌ 文件发送失败，请联系客服"
        },
        "help": {
            "title": "❓ 使用帮助",
            "instructions": "❗使用说明",
            "instructions_simple": "使用说明"
        },
        "error": {
            "load_failed": "❌ 加载失败，请重试",
            "no_permission": "❌ 无权限",
            "invalid_amount": "❌ 金额必须大于0，请重新输入",
            "invalid_format": "❌ 金额格式错误，请输入数字",
            "invalid_address": "❌ 地址长度不正确，请重新输入",
            "close": "❌ 关闭",
            "cancel_transaction": "❌ 取消交易",
            "invalid_integer": "❌ 请输入有效整数",
            "quantity_required": "❌ 数量需 > 0",
            "download_failed": "❌ 下载失败，请稍后重试",
            "invalid_number": "❌ 金额格式错误，请输入数字（例如 12 或 12.5）",
            "processing_error": "❌ 处理异常，请重试",
            "search_expired": "搜索已过期，请重新搜索",
            "operation_failed": "操作失败",
            "invalid_params": "参数错误",
            "amount_format_error": "金额格式错误",
            "cannot_cancel": "无法取消（已过期/已支付/不存在）",
            "cancel_failed": "取消失败",
            "unknown_operation": "❓ 未知操作"
        },
        "success": {
            "file_resent": "✅ 文件已重新发送，请查收！"
        },
        "general": {
            "view_transaction": "🔎 查看交易",
            "view_address": "📬 查看地址",
            "toggle_status": "🔄 切换状态",
            "announcement": "<b>📢 最新公告</b>\n\n{message_text}"
        }
    },
    "en": {
        "common": {
            "back_main": "🏠 Main Menu",
            "back": "🔙 Back",
            "not_set": "Not set",
            "back_to_main": "🏠 Back to Main",
            "refresh": "🔄 Refresh",
            "cancel": "🔙 Cancel",
            "prev_page": "⬅️ Previous",
            "next_page": "➡️ Next",
            "init_failed": "Initialization failed, please try again later",
            "latest_state": "Interface is up to date",
            "refresh_failed": "Refresh failed, please try again",
            "interface_latest": "Interface is latest",
            "operation_exception": "Operation exception",
            "no_permission": "No permission",
            "cancelled": "Cancelled",
            "unit": "pcs"
        },
        "start": {
            "welcome": "🎉 Welcome to {agent_name}!",
            "user_info": "👤 User Information",
            "user_id": "• ID: {uid}",
            "username": "• Username: @{username}",
            "nickname": "• Nickname: {nickname}",
            "select_function": "Please select a function:"
        },
        "main_menu": {
            "title": "🏠 Main Menu",
            "current_time": "Current time: {time}"
        },
        "btn": {
            "products": "🛍️ Products",
            "profile": "👤 Profile",
            "recharge": "💰 Recharge",
            "orders": "📊 Orders",
            "support": "📞 Support",
            "help": "❓ Help",
            "price_management": "💰 Price Management",
            "system_reports": "📊 System Reports",
            "profit_center": "💸 Profit Center",
            "language": "🌐 语言 / Language",
            "back_main": "🏠 Main Menu",
            "back_to_list": "🔙 Back to List",
            "back_to_management": "🔙 Back to Management",
            "back_to_edit": "🔙 Back to Edit"
        },
        "lang": {
            "menu_title": "🌐 语言选择 / Language Selection",
            "zh_label": "🇨🇳 中文",
            "en_label": "🇬🇧 English",
            "set_ok": "✅ Language switched"
        },
        "products": {
            "center": "🛍️ Product Center",
            "view": "🧾 View Product",
            "categories": {
                "title": "🛒 Product Categories - Please select:",
                "search_tip": "❗Quick search by country code (e.g., +54)",
                "first_purchase_tip": "❗️First-time buyers please test with small quantities!",
                "inactive_tip": "❗️Long-inactive accounts may have issues. Contact support.",
                "no_categories": "❌ No product categories available"
            },
            "not_exist": "❌ Product does not exist",
            "back_to_list": "🔙 Back to Product List",
            "price_not_set": "❌ Product price not set",
            "buy": "✅ Buy",
            "confirm_purchase": "✅ Confirm Purchase",
            "continue_shopping": "🛍️ Continue Shopping",
            "purchase_success": "✅ Purchase successful!",
            "purchase_failed": "❌ Purchase failed: {res}",
            "no_products_wait": "No products available, please wait",
            "insufficient_stock": "❌ Insufficient stock (current {stock})",
            "no_products_to_manage": "❌ No products to manage",
            "cannot_find": "❌ Cannot find product information",
            "no_longer_exists": "❌ Product no longer exists",
            "file_not_found": "⚠️ Original product file not found, attempting to retrieve...",
            "purchasing": "🛒 Purchasing Product",
            "out_of_stock": "⚠️ Out of stock",
            "purchase_status": "✅You are purchasing:",
            "price_label": "💰 Price: {price:.2f} USDT",
            "stock_label": "📦 Stock: {stock} pcs",
            "purchase_warning": "❗For first-time purchases from our store, please buy in small quantities for testing to avoid unnecessary disputes! Thank you for your cooperation!",
            "country_list": "🌍 {title} Product List ({codes_display})",
            "country_product": "{name} | {price}U | [{stock} pcs]"
        },
        "orders": {
            "title": "📊 Order History",
            "purchase_records": "📦 Purchase Records",
            "no_records": "No purchase records",
            "cancel_order": "❌ Cancel Order",
            "not_exist": "❌ Order does not exist or no access",
            "details": "📋 Order Details",
            "load_failed": "❌ Failed to load order details",
            "overview": "📊 Records Overview",
            "total_orders": "• Total Orders: {total}",
            "current_page": "• Current Page: {count}",
            "recent_update": "• Recent Update: {time}",
            "operation_guide": "💡 Operation Guide",
            "operation_tip": "Click the buttons below to view order details or re-download products"
        },
        "recharge": {
            "title": "💰 Recharge Balance",
            "balance_recharge": "💰 Balance Recharge",
            "records": "📜 Recharge Records",
            "recent_records_empty": "📜 Recent Recharge Records\n\nNo records",
            "recent_records": "📜 Recent Recharge Records (Latest First)",
            "back_to_recharge": "🔙 Back to Recharge",
            "exceed_balance": "❌ Exceeds withdrawable balance {balance:.2f}, please re-enter",
            "insufficient_balance": "❌ Insufficient balance, need: {total_cost:.2f}U current: {bal:.2f}U",
            "amount_generated": "Amount generated, please transfer according to the payable amount"
        },
        "profit": {
            "center": "💸 Profit Center",
            "apply_withdrawal": "📝 Apply for Withdrawal",
            "application_records": "📋 Application Records",
            "no_withdrawable": "⚠️ No withdrawable profit currently",
            "back_to_center": "💸 Back to Profit Center",
            "budget": "📊 Profit Budget",
            "calculator": "📊 Profit Calculator - {name}\nHQ: {op}U (Real-time Price)",
            "withdrawal_apply": "📝 Apply for Withdrawal",
            "withdrawal_records_empty": "📋 Withdrawal Records\n\nNo applications",
            "withdrawal_records": "📋 Withdrawal Records (Latest First)",
            "withdrawal_success": "✅ Withdrawal application successful\nAmount: {amt:.2f} USDT\nAddress: {address}\nStatus: Pending Review",
            "amount_recorded": "✅ Amount recorded: {amt:.2f} USDT\nPlease send receiving address (TRON or ERC20)"
        },
        "price": {
            "management": "💰 Price Management (Page {page})",
            "config_not_exist": "❌ Agent price configuration does not exist",
            "invalid_price": "❌ Please enter a valid price number",
            "below_hq_price": "❌ Agent price cannot be lower than HQ price {op} USDT",
            "set_rate": "Set {rate}%({new_agent_price})",
            "update_success": "Price update successful! Markup {new_markup:.2f}U, profit rate {profit_rate:.1f}% (based on current HQ price {op}U)",
            "no_change": "No change",
            "below_hq_error": "Agent price cannot be lower than HQ price {op} USDT (current HQ price), your input {new_agent_price} USDT is below HQ price",
            "product_not_exist": "Original product does not exist"
        },
        "reports": {
            "center": "📊 System Reports Center",
            "sales": "📈 Sales Report ({days} days)",
            "sales_30d": "📈 Sales Report (30 days)",
            "user_report": "👥 User Report",
            "user_stats": "👥 User Statistics Report",
            "product_report": "📦 Product Report",
            "product_stats": "📦 Product Statistics Report",
            "financial": "💰 Financial Report ({days} days)",
            "financial_30d": "💰 Financial Report (30 days)",
            "overview": "📊 System Overview Report (30 days)",
            "overview_btn": "📊 Comprehensive Overview",
            "refresh": "🔄 Refresh Data",
            "back_to_reports": "🔙 Back to Reports",
            "7days": "📅 7 Days",
            "30days": "📅 30 Days",
            "90days": "📅 90 Days"
        },
        "user": {
            "profile": "👤 Profile",
            "contact": "👤 Contact User",
            "info_not_exist": "❌ User information does not exist",
            "admin_reloaded": "✅ Admin list reloaded\n\nCurrent admin user IDs:\n{admin_list}",
            "admin_reload_no_config": "⚠️ Admin list reloaded, but no admin configured"
        },
        "support": {
            "title": "📞 Contact Support",
            "contact": "💬 Contact Support",
            "description": "📞 Support {display}\nPlease describe the issue + User ID/Order No. for quick processing.",
            "file_send_failed": "❌ File send failed, please contact support"
        },
        "help": {
            "title": "❓ Help",
            "instructions": "❗Instructions",
            "instructions_simple": "Instructions"
        },
        "error": {
            "load_failed": "❌ Load failed, please try again",
            "no_permission": "❌ No permission",
            "invalid_amount": "❌ Amount must be greater than 0, please re-enter",
            "invalid_format": "❌ Invalid format, please enter a number",
            "invalid_address": "❌ Incorrect address length, please re-enter",
            "close": "❌ Close",
            "cancel_transaction": "❌ Cancel Transaction",
            "invalid_integer": "❌ Please enter a valid integer",
            "quantity_required": "❌ Quantity must be > 0",
            "download_failed": "❌ Download failed, please try again later",
            "invalid_number": "❌ Invalid format, please enter a number (e.g., 12 or 12.5)",
            "processing_error": "❌ Processing error, please try again",
            "search_expired": "Search expired, please search again",
            "operation_failed": "Operation failed",
            "invalid_params": "Invalid parameters",
            "amount_format_error": "Amount format error",
            "cannot_cancel": "Cannot cancel (expired/paid/does not exist)",
            "cancel_failed": "Cancel failed",
            "unknown_operation": "❓ Unknown operation"
        },
        "success": {
            "file_resent": "✅ File resent successfully, please check!"
        },
        "general": {
            "view_transaction": "🔎 View Transaction",
            "view_address": "📬 View Address",
            "toggle_status": "🔄 Toggle Status",
            "announcement": "<b>📢 Latest Announcement</b>\n\n{message_text}"
        }
    }
}

class AgentBotConfig:
    """代理机器人配置"""
    def __init__(self):
        if len(sys.argv) > 1 and not sys.argv[-1].startswith("--env"):
            self.BOT_TOKEN = sys.argv[1]
        else:
            env_token = os.getenv("BOT_TOKEN")
            if not env_token:
                raise ValueError("请提供机器人Token：命令行参数 <BOT_TOKEN> 或环境变量 BOT_TOKEN")
            self.BOT_TOKEN = env_token

        self.MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/")
        self.DATABASE_NAME = os.getenv("DATABASE_NAME", "9haobot")
        self.AGENT_BOT_ID = os.getenv("AGENT_BOT_ID", "62448807124351dfe5cc48d4")
        self.AGENT_NAME = os.getenv("AGENT_NAME", "华南代理机器人")
        self.FILE_BASE_PATH = os.getenv("FILE_BASE_PATH", "/www/9haobot/222/9hao-main")

        self.AGENT_USDT_ADDRESS = os.getenv("AGENT_USDT_ADDRESS")
        if not self.AGENT_USDT_ADDRESS:
            raise ValueError("未设置 AGENT_USDT_ADDRESS，请在环境变量中配置代理收款地址（TRC20）")

        # 有效期设为 10 分钟（可用环境变量覆盖）
        self.RECHARGE_EXPIRE_MINUTES = int(os.getenv("RECHARGE_EXPIRE_MINUTES", "10"))
        if self.RECHARGE_EXPIRE_MINUTES <= 0:
            self.RECHARGE_EXPIRE_MINUTES = 10

        self.RECHARGE_MIN_USDT = Decimal(os.getenv("RECHARGE_MIN_USDT", "10")).quantize(Decimal("0.01"))
        self.RECHARGE_DECIMALS = 4
        self.RECHARGE_POLL_INTERVAL_SECONDS = int(os.getenv("RECHARGE_POLL_INTERVAL_SECONDS", "8"))
        if self.RECHARGE_POLL_INTERVAL_SECONDS < 3:
            self.RECHARGE_POLL_INTERVAL_SECONDS = 3

        self.TOKEN_SYMBOL = os.getenv("TOKEN_SYMBOL", "USDT")
        self.USDT_TRON_CONTRACT = os.getenv("USDT_TRON_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
        self.TRONSCAN_TRX20_API = os.getenv("TRONSCAN_TRX20_API", "https://apilist.tronscanapi.com/api/token_trc20/transfers")

        self.TRON_API_KEYS = [k.strip() for k in os.getenv("TRON_API_KEYS", "").split(",") if k.strip()]
        self.TRONGRID_API_BASE = os.getenv("TRONGRID_API_BASE", "https://api.trongrid.io").rstrip("/")
        self.TRON_API_KEY_HEADER = os.getenv("TRON_API_KEY_HEADER", "TRON-PRO-API-KEY")
        self._tron_key_index = 0

        # ✅ 代理自己的通知群
        self.AGENT_NOTIFY_CHAT_ID = os.getenv("AGENT_NOTIFY_CHAT_ID")
        if not self.AGENT_NOTIFY_CHAT_ID:
            logger.warning("⚠️ 未设置 AGENT_NOTIFY_CHAT_ID，订单通知可能无法发送")
        
        # ✅ 总部通知群
        self.HEADQUARTERS_NOTIFY_CHAT_ID = HEADQUARTERS_NOTIFY_CHAT_ID
        if not self.HEADQUARTERS_NOTIFY_CHAT_ID:
            logger.warning("⚠️ 未设置 HEADQUARTERS_NOTIFY_CHAT_ID")
        
        # ✅ 代理补货通知群（回退到AGENT_NOTIFY_CHAT_ID）
        self.AGENT_RESTOCK_NOTIFY_CHAT_ID = AGENT_RESTOCK_NOTIFY_CHAT_ID or self.AGENT_NOTIFY_CHAT_ID
        if not self.AGENT_RESTOCK_NOTIFY_CHAT_ID:
            logger.warning("⚠️ 未设置 AGENT_RESTOCK_NOTIFY_CHAT_ID 或 AGENT_NOTIFY_CHAT_ID，补货通知可能无法发送")
        
        # ✅ 补货通知关键词配置（支持中英文）
        default_keywords = "补货通知,库存更新,新品上架,restock,new stock,inventory update"
        self.RESTOCK_KEYWORDS = [k.strip() for k in os.getenv("RESTOCK_KEYWORDS", default_keywords).split(",") if k.strip()]
        
        # ✅ 补货通知按钮重写开关（默认关闭，提高安全性）
        # 支持两个环境变量名：HQ_RESTOCK_REWRITE_BUTTONS（新）和 RESTOCK_REWRITE_BUTTONS（旧，兼容性）
        button_rewrite_flag = os.getenv("HQ_RESTOCK_REWRITE_BUTTONS") or os.getenv("RESTOCK_REWRITE_BUTTONS", "0")
        self.HQ_RESTOCK_REWRITE_BUTTONS = button_rewrite_flag in ("1", "true", "True")

        # 取消订单后是否删除原消息 (默认删除)
        self.RECHARGE_DELETE_ON_CANCEL = os.getenv("RECHARGE_DELETE_ON_CANCEL", "1") in ("1", "true", "True")
        
        # ✅ 商品同步配置
        self.AGENT_ENABLE_PRODUCT_WATCH = os.getenv("AGENT_ENABLE_PRODUCT_WATCH", "1") in ("1", "true", "True")
        self.PRODUCT_SYNC_POLL_SECONDS = int(os.getenv("PRODUCT_SYNC_POLL_SECONDS", "120"))
        if self.PRODUCT_SYNC_POLL_SECONDS < 30:
            self.PRODUCT_SYNC_POLL_SECONDS = 30  # 最小30秒
        
        # ✅ 协议号分类统一配置
        self.AGENT_PROTOCOL_CATEGORY_UNIFIED = AGENT_PROTOCOL_CATEGORY_UNIFIED
        # 解析别名，并包含 None 和空字符串
        aliases_str = AGENT_PROTOCOL_CATEGORY_ALIASES
        self.AGENT_PROTOCOL_CATEGORY_ALIASES = [a.strip() for a in aliases_str.split(",") if a.strip() or a == ""]
        # 确保包含空字符串和会被映射为None的情况
        if "" not in self.AGENT_PROTOCOL_CATEGORY_ALIASES:
            self.AGENT_PROTOCOL_CATEGORY_ALIASES.append("")
        
        # ✅ 零库存分类显示配置
        self.AGENT_SHOW_EMPTY_CATEGORIES = os.getenv("AGENT_SHOW_EMPTY_CATEGORIES", "1") in ("1", "true", "True")
        
        # ✅ HQ克隆模式配置（需求：克隆总部分类显示）
        self.AGENT_CLONE_HEADQUARTERS_CATEGORIES = os.getenv("AGENT_CLONE_HEADQUARTERS_CATEGORIES", "1") in ("1", "true", "True")
        
        # ✅ 协议号分类在总部分类中的位置（默认第2位，即索引1）
        self.HQ_PROTOCOL_CATEGORY_INDEX = int(os.getenv("HQ_PROTOCOL_CATEGORY_INDEX", "2"))
        
        # ✅ 协议号主分类和老号分类名称
        self.HQ_PROTOCOL_MAIN_CATEGORY_NAME = os.getenv("HQ_PROTOCOL_MAIN_CATEGORY_NAME", "🔥二手TG协议号（session+json）")
        self.HQ_PROTOCOL_OLD_CATEGORY_NAME = os.getenv("HQ_PROTOCOL_OLD_CATEGORY_NAME", "✈️【1-8年】协议老号（session+json）")
        
        # ✅ 协议号关键词列表（用于检测协议号类商品）
        keywords_str = os.getenv("AGENT_PROTOCOL_CATEGORY_KEYWORDS", "协议,协议号,年老号,老号,[1-8],[3-8],【1-8年】,【3-8年】")
        self.AGENT_PROTOCOL_CATEGORY_KEYWORDS = [kw.strip() for kw in keywords_str.split(",") if kw.strip()]
        
        # ✅ 老号协议关键词（用于识别老号协议）
        old_keywords_str = os.getenv("AGENT_PROTOCOL_OLD_KEYWORDS", "年老号,老号")
        self.AGENT_PROTOCOL_OLD_KEYWORDS = [kw.strip() for kw in old_keywords_str.split(",") if kw.strip()]
        
        # ✅ 默认代理加价（新商品自动同步时的默认加价）
        self.AGENT_DEFAULT_MARKUP = float(os.getenv("AGENT_DEFAULT_MARKUP", "0.2"))
        
        # ✅ 客服联系方式配置
        self.SUPPORT_CONTACT_USERNAME = os.getenv("SUPPORT_CONTACT_USERNAME", "9haokf")
        self.SUPPORT_CONTACT_URL = os.getenv("SUPPORT_CONTACT_URL") or f"https://t.me/{self.SUPPORT_CONTACT_USERNAME}"
        self.SUPPORT_CONTACT_DISPLAY = os.getenv("SUPPORT_CONTACT_DISPLAY")
        
        # ✅ 广告推送配置
        self.AGENT_AD_CHANNEL_ID = os.getenv("AGENT_AD_CHANNEL_ID")
        self.AGENT_AD_DM_ENABLED = os.getenv("AGENT_AD_DM_ENABLED", "0") in ("1", "true", "True")
        self.AGENT_AD_DM_ACTIVE_DAYS = int(os.getenv("AGENT_AD_DM_ACTIVE_DAYS", "0"))
        self.AGENT_AD_DM_MAX_PER_RUN = int(os.getenv("AGENT_AD_DM_MAX_PER_RUN", "0"))
        
        # ✅ 广告推送完成通知配置（独立于 AGENT_NOTIFY_CHAT_ID）
        self.AGENT_AD_NOTIFY_CHAT_ID = os.getenv("AGENT_AD_NOTIFY_CHAT_ID")
        
        if self.AGENT_AD_DM_ENABLED:
            if not self.AGENT_AD_CHANNEL_ID:
                logger.warning("⚠️ AGENT_AD_DM_ENABLED=1 但未设置 AGENT_AD_CHANNEL_ID，广告推送功能无法工作")
            else:
                logger.info(f"✅ 广告推送已启用: channel_id={self.AGENT_AD_CHANNEL_ID}, active_days={self.AGENT_AD_DM_ACTIVE_DAYS}, max_per_run={self.AGENT_AD_DM_MAX_PER_RUN}")
                if self.AGENT_AD_NOTIFY_CHAT_ID:
                    logger.info(f"✅ 广告推送完成通知已配置: notify_chat_id={self.AGENT_AD_NOTIFY_CHAT_ID}")
        else:
            # 显示配置状态，帮助用户了解如何启用
            if self.AGENT_AD_CHANNEL_ID:
                logger.info(f"ℹ️ 广告推送功能已禁用（AGENT_AD_DM_ENABLED=0），已配置频道: {self.AGENT_AD_CHANNEL_ID}")
            else:
                logger.info("ℹ️ 广告推送功能已禁用（AGENT_AD_DM_ENABLED=0），未配置 AGENT_AD_CHANNEL_ID")

        try:
            self.client = MongoClient(self.MONGODB_URI)
            self.db = self.client[self.DATABASE_NAME]
            self.client.admin.command('ping')
            logger.info("✅ 数据库连接成功")

            self.ejfl = self.db['ejfl']
            self.hb = self.db['hb']
            self.fenlei = self.db['fenlei']  # ✅ 总部分类表
            self.agent_product_prices = self.db['agent_product_prices']
            self.agent_profit_account = self.db['agent_profit_account']
            self.withdrawal_requests = self.db['withdrawal_requests']
            self.recharge_orders = self.db['recharge_orders']
        except Exception as e:
            logger.error(f"❌ 数据库连接失败: {e}")
            raise
        
        # ✅ 管理员配置
        self.ADMIN_USERS: List[int] = []
        self._load_admins_from_env()
        self._load_admins_from_db()
        if not self.ADMIN_USERS:
            logger.warning("⚠️ 未配置管理员用户，管理功能将不可用。请通过 ADMIN_USERS 环境变量或 agent_admins 数据库表配置管理员。")

    def get_agent_user_collection(self):
        suffix = self.AGENT_BOT_ID[6:] if self.AGENT_BOT_ID.startswith('agent_') else self.AGENT_BOT_ID
        return self.db[f'agent_users_{suffix}']

    def get_agent_gmjlu_collection(self):
        suffix = self.AGENT_BOT_ID[6:] if self.AGENT_BOT_ID.startswith('agent_') else self.AGENT_BOT_ID
        return self.db[f'agent_gmjlu_{suffix}']

    def _next_tron_api_key(self) -> Optional[str]:
        if not self.TRON_API_KEYS:
            return None
        key = self.TRON_API_KEYS[self._tron_key_index % len(self.TRON_API_KEYS)]
        self._tron_key_index = (self._tron_key_index + 1) % max(len(self.TRON_API_KEYS), 1)
        return key
    
    def _load_admins_from_env(self):
        """从环境变量 ADMIN_USERS 加载管理员用户ID列表"""
        env_admins = os.getenv("ADMIN_USERS", "").strip()
        if not env_admins:
            return
        
        # 支持逗号和空格分隔
        # 将逗号替换为空格，然后按空格分割
        tokens = re.split(r'[,\s]+', env_admins)
        
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            try:
                user_id = int(token)
                if user_id not in self.ADMIN_USERS:
                    self.ADMIN_USERS.append(user_id)
            except ValueError:
                logger.warning(f"⚠️ 环境变量 ADMIN_USERS 中的无效用户ID: {token}")
        
        if self.ADMIN_USERS:
            logger.info(f"✅ 从环境变量加载了 {len(self.ADMIN_USERS)} 个管理员用户")
    
    def _load_admins_from_db(self):
        """从 MongoDB agent_admins 集合加载管理员用户ID列表"""
        try:
            collection = self.db['agent_admins']
            query = {
                "agent_bot_id": self.AGENT_BOT_ID,
                "enabled": True,
                "role": {"$in": ["admin", "superadmin"]}
            }
            
            docs = collection.find(query)
            count = 0
            for doc in docs:
                user_id = doc.get('user_id')
                if user_id and isinstance(user_id, int):
                    if user_id not in self.ADMIN_USERS:
                        self.ADMIN_USERS.append(user_id)
                        count += 1
            
            if count > 0:
                logger.info(f"✅ 从数据库加载了 {count} 个管理员用户")
        except Exception as e:
            logger.info(f"ℹ️ 从数据库加载管理员失败（可能集合不存在）: {e}")
    
    def reload_admins(self):
        """重新加载管理员列表"""
        self.ADMIN_USERS.clear()
        self._load_admins_from_env()
        self._load_admins_from_db()
        logger.info(f"✅ 管理员列表已重新加载，当前管理员: {self.ADMIN_USERS}")
        return self.ADMIN_USERS
    
    def is_admin(self, user_id: int) -> bool:
        """检查用户是否为管理员"""
        return int(user_id) in self.ADMIN_USERS


class AgentBotCore:
    """核心业务"""

    def __init__(self, config: AgentBotConfig):
        self.config = config

    # ---------- 时间/工具 ----------
    def _to_beijing(self, dt: datetime) -> datetime:
        """UTC -> 北京时间（UTC+8）"""
        if dt is None:
            dt = datetime.utcnow()
        return dt + timedelta(hours=8)
    
    def _safe_price(self, money_field: Any) -> float:
        """安全解析价格字段，处理空值、字符串等异常情况"""
        try:
            if money_field is None:
                return 0.0
            if isinstance(money_field, (int, float)):
                return float(money_field)
            if isinstance(money_field, str):
                money_field = money_field.strip()
                if not money_field:
                    return 0.0
                return float(money_field)
            return 0.0
        except (ValueError, TypeError):
            return 0.0
    
    def _unify_category(self, leixing: Any) -> str:
        """统一分类：将协议号类的别名都映射到统一分类"""
        # None 也视作别名
        if leixing is None or leixing in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES:
            return self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED
        return leixing
    
    def _is_protocol_like_product(self, name: str, leixing: Any) -> bool:
        """
        检测商品是否为协议号类商品（HQ克隆模式使用）
        
        检测规则（按优先级）：
        1. leixing 在别名列表中或等于统一分类名 -> True（已标记为协议号）
        2. projectname 包含关键词（协议、协议号、年老号、老号等）-> True（检测误标记）
        3. projectname 包含年份范围模式（如 [1-8] 或 [3-8 年]）-> True（检测误标记）
        4. leixing 为 None/空 -> True（未分类商品归入协议号）
        
        Args:
            name: 商品名称 (projectname)
            leixing: 商品分类 (leixing)
        
        Returns:
            True 如果商品应归入协议号分类，否则 False
        """
        # 规则1: leixing 在别名列表中或等于统一分类名（已经是协议号类）
        if leixing in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES:
            return True
        if leixing == self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
            return True
        
        # 规则2: 检查商品名称是否包含协议号关键词（检测误标记的协议号商品）
        if name:
            for keyword in self.config.AGENT_PROTOCOL_CATEGORY_KEYWORDS:
                if keyword and keyword in name:
                    return True
            
            # 规则3: 检查年份范围模式（检测误标记的协议号商品）
            year_range_pattern = r'\[\s*\d+\s*-\s*\d+\s*(?:年)?\s*\]'
            if re.search(year_range_pattern, name):
                return True
        
        # 规则4: leixing 为 None/空（未分类商品默认归入协议号）
        if leixing is None or leixing == '':
            return True
        
        return False
    
    def _is_protocol_like(self, name: str, leixing: Any) -> bool:
        """
        检测商品是否为协议号类商品（新版：用于双分类）
        
        检测规则：
        1. leixing 在别名列表中或等于主/老分类名 -> True
        2. projectname 包含协议号关键词 -> True
        3. projectname 包含年份范围模式 -> True
        4. leixing 为 None/空 -> True
        
        Args:
            name: 商品名称 (projectname)
            leixing: 商品分类 (leixing)
        
        Returns:
            True 如果商品应归入协议号分类（主或老），否则 False
        """
        # 规则1: leixing 匹配协议号分类
        if leixing in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES:
            return True
        if leixing == self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
            return True
        if leixing == self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME:
            return True
        if leixing == self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME:
            return True
        
        # 规则2: 检查商品名称是否包含协议号关键词
        if name:
            for keyword in self.config.AGENT_PROTOCOL_CATEGORY_KEYWORDS:
                if keyword and keyword in name:
                    return True
        
        # 规则3: leixing 为 None/空
        if leixing is None or leixing == '':
            return True
        
        return False
    
    def _is_old_protocol(self, name: str) -> bool:
        """
        检测商品是否为老号协议
        
        检测规则：
        1. 名称包含年份范围模式（如 [1-8年]、【3-8年】等）-> True
        2. 名称包含老号关键词（年老号、老号等）-> True
        
        Args:
            name: 商品名称 (projectname)
        
        Returns:
            True 如果商品应归入老号协议分类，否则 False
        """
        if not name:
            return False
        
        # 规则1: 检查年份范围模式（支持中英文括号）
        year_range_pattern = r'[\[【]\s*\d+\s*-\s*\d+\s*(?:年)?\s*[】\]]'
        if re.search(year_range_pattern, name):
            return True
        
        # 规则2: 检查老号关键词
        for keyword in self.config.AGENT_PROTOCOL_OLD_KEYWORDS:
            if keyword and keyword in name:
                return True
        
        return False
    
    def _classify_protocol_subcategory(self, name: str, leixing: Any) -> Optional[str]:
        """
        分类协议号商品到具体子分类
        
        Args:
            name: 商品名称 (projectname)
            leixing: 商品分类 (leixing)
        
        Returns:
            - HQ_PROTOCOL_OLD_CATEGORY_NAME 如果是老号协议
            - HQ_PROTOCOL_MAIN_CATEGORY_NAME 如果是主协议号
            - None 如果不是协议号类商品
        """
        # 首先检查是否为协议号类商品
        if not self._is_protocol_like(name, leixing):
            return None
        
        # 然后检查是否为老号协议
        if self._is_old_protocol(name):
            return self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME
        
        # 否则归入主协议号分类
        return self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME

    # ---------- UI 辅助 ----------
    def _h(self, s: Any) -> str:
        try:
            return html_escape(str(s) if s is not None else "", quote=False)
        except Exception:
            return str(s or "")

    def _link_user(self, user_id: int) -> str:
        return f"<a href='tg://user?id={user_id}'>{user_id}</a>"

    def _tronscan_tx_url(self, tx_id: str) -> str:
        return f"https://tronscan.org/#/transaction/{tx_id}"

    def _tronscan_addr_url(self, address: str) -> str:
        return f"https://tronscan.org/#/address/{address}"

    def _kb_product_actions(self, nowuid: str, user_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🧾 查看商品", callback_data=f"product_{nowuid}"),
             InlineKeyboardButton("👤 联系用户", url=f"tg://user?id={user_id}")]
        ])

    def _kb_tx_addr_user(self, tx_id: Optional[str], address: str, user_id: int):
        btns = []
        row = []
        if tx_id:
            row.append(InlineKeyboardButton("🔎 查看交易", url=self._tronscan_tx_url(tx_id)))
        if address:
            row.append(InlineKeyboardButton("📬 查看地址", url=self._tronscan_addr_url(address)))
        if row:
            btns.append(row)
        btns.append([InlineKeyboardButton("👤 联系用户", url=f"tg://user?id={user_id}")])
        return InlineKeyboardMarkup(btns)
    
    def _kb_purchase_notify(self, nowuid: str, user_id: int) -> InlineKeyboardMarkup:
        """购买通知按钮布局（新版）"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🧾 查看商品", callback_data=f"product_{nowuid}"),
             InlineKeyboardButton("👤 联系用户", url=f"tg://user?id={user_id}")]
        ])
    
    def build_purchase_notify_text(
        self,
        user_id: int,
        product_name: str,
        category: str,
        nowuid: str,
        quantity: int,
        profit_per_unit: float,
        origin_price: float,
        agent_price: float,
        total_value: float,
        total_profit: float,
        before_balance: float,
        after_balance: float,
        total_spent_after: float,
        total_orders_after: int,
        avg_order_value: float,
        sale_time_beijing: str,
        order_id: str,
        bot_username: str = None
    ) -> str:
        """
        构建购买成功群通知文本（新版格式）
        
        Args:
            user_id: 用户ID
            product_name: 商品名称
            category: 商品分类
            nowuid: 商品唯一ID
            quantity: 购买数量
            profit_per_unit: 单件利润（加价）
            origin_price: 总部原价
            agent_price: 代理单价
            total_value: 订单总价值
            total_profit: 本单利润
            before_balance: 扣款前余额
            after_balance: 扣款后余额
            total_spent_after: 累计消费
            total_orders_after: 总订单数
            avg_order_value: 平均订单价值
            sale_time_beijing: 销售时间（北京时间）
            order_id: 订单号
            bot_username: 机器人用户名（可选）
        
        Returns:
            格式化的HTML文本（整体加粗）
        """
        # 如果没有提供bot_username，使用AGENT_NAME作为回退
        username = bot_username if bot_username else self.config.AGENT_NAME
        
        text = (
            "<b>🛒收到了一份 采购订单 🛍\n"
            f"❇️用户名：@{self._h(username)}\n"
            f"💵利润加价: {profit_per_unit:.2f}U\n"
            f"🧾 订单号：</b><code>{self._h(order_id)}</code><b>\n"
            f"🏢 代理ID：</b><code>{self._h(self.config.AGENT_BOT_ID)}</code><b>\n"
            "➖➖➖➖➖➖\n"
            f"🗓日期|时间： {self._h(sale_time_beijing)}\n"
            f"❤️来自用户：</b><code>{user_id}</code><b>\n"
            f"🗂 分类：{self._h(category)}\n"
            f"📦 商品：{self._h(product_name)}\n"
            f"☑️购买数量：{quantity}\n"
            f"💰订单总价值：{total_value:.2f}U\n"
            f"🌐总部原价: {origin_price:.2f}U\n"
            f"💰 单价（代理）：{agent_price:.2f}U\n"
            f"💵 本单利润：{total_profit:.2f}U\n"
            f"💸用户旧余额 : {before_balance:.2f}U\n"
            f"🟢用户当前余额：{after_balance:.2f}U\n"
            f"📊 累计消费：{total_spent_after:.2f}U（共 {total_orders_after} 单，平均 {avg_order_value:.2f}U）\n"
            "➖➖➖➖➖➖\n"
            f"💎您从这笔交易中获得的利润({quantity} * {profit_per_unit:.2f})：{total_profit:.2f}U</b>"
        )
        return text

    # ---------- 用户与商品 ----------
    def register_user(self, user_id: int, username: str = "", first_name: str = "") -> bool:
        try:
            coll = self.config.get_agent_user_collection()
            exist = coll.find_one({'user_id': user_id})
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if exist:
                coll.update_one({'user_id': user_id}, {'$set': {'last_active': now}})
                return True
            max_user = coll.find_one({}, sort=[("count_id", -1)])
            count_id = (max_user.get('count_id', 0) + 1) if max_user else 1
            coll.insert_one({
                'user_id': user_id,
                'count_id': count_id,
                'username': username,
                'first_name': first_name,
                'fullname': first_name,
                'USDT': 0.0,
                'zgje': 0.0,
                'zgsl': 0,
                'creation_time': now,
                'register_time': now,
                'last_active': now,
                'last_contact_time': now,
                'status': 'active',
                'language': DEFAULT_LANGUAGE
            })
            logger.info(f"✅ 用户注册成功 {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 用户注册失败: {e}")
            return False

    def get_user_info(self, user_id: int) -> Optional[Dict]:
        try:
            return self.config.get_agent_user_collection().find_one({'user_id': user_id})
        except Exception as e:
            logger.error(f"❌ 获取用户信息失败: {e}")
            return None

    # ---------- 语言管理 ----------
    def get_user_language(self, user_id: int) -> str:
        """
        获取用户的语言偏好
        
        Args:
            user_id: 用户ID
        
        Returns:
            语言代码（'zh' 或 'en'），默认返回 DEFAULT_LANGUAGE
        """
        try:
            user_info = self.get_user_info(user_id)
            if user_info and 'language' in user_info:
                lang = user_info['language']
                if lang in I18N:
                    return lang
            return DEFAULT_LANGUAGE
        except Exception as e:
            logger.error(f"❌ 获取用户语言失败: {e}")
            return DEFAULT_LANGUAGE

    def set_user_language(self, user_id: int, lang: str) -> bool:
        """
        设置用户的语言偏好
        
        Args:
            user_id: 用户ID
            lang: 语言代码（'zh' 或 'en'）
        
        Returns:
            True 如果设置成功，否则 False
        """
        try:
            if lang not in I18N:
                logger.warning(f"⚠️ 不支持的语言代码: {lang}")
                return False
            
            coll = self.config.get_agent_user_collection()
            result = coll.update_one(
                {'user_id': user_id},
                {'$set': {'language': lang}}
            )
            
            if result.modified_count > 0 or result.matched_count > 0:
                logger.info(f"✅ 用户 {user_id} 语言已设置为 {lang}")
                return True
            else:
                logger.warning(f"⚠️ 用户 {user_id} 不存在，无法设置语言")
                return False
        except Exception as e:
            logger.error(f"❌ 设置用户语言失败: {e}")
            return False

    def t(self, user_id: int, key: str, **kwargs) -> str:
        """
        翻译助手函数
        
        Args:
            user_id: 用户ID
            key: 翻译键（点号分隔，如 'start.welcome'）
            **kwargs: 格式化参数
        
        Returns:
            翻译后的文本，如果键不存在则返回键本身
        """
        try:
            lang = self.get_user_language(user_id)
            keys = key.split('.')
            value = I18N[lang]
            
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    logger.warning(f"⚠️ 翻译键不存在: {key} (lang={lang})")
                    return key
            
            if isinstance(value, str) and kwargs:
                return value.format(**kwargs)
            return value
        except Exception as e:
            logger.error(f"❌ 翻译失败 key={key}: {e}")
            return key

    def broadcast_ad_to_agent_users(self, message_text: str, parse_mode: str = ParseMode.HTML) -> int:
        """
        广播广告消息到所有代理用户的私聊
        
        Args:
            message_text: 要发送的消息文本
            parse_mode: 消息解析模式（默认HTML）
        
        Returns:
            成功发送的用户数量
        """
        try:
            # 构建查询条件
            query = {}
            
            # 根据活跃天数过滤
            if self.config.AGENT_AD_DM_ACTIVE_DAYS > 0:
                cutoff_date = datetime.now() - timedelta(days=self.config.AGENT_AD_DM_ACTIVE_DAYS)
                cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
                query['last_active'] = {'$gte': cutoff_str}
                logger.info(f"📊 广告推送筛选条件: 最近 {self.config.AGENT_AD_DM_ACTIVE_DAYS} 天活跃用户（{cutoff_str} 之后）")
            else:
                logger.info("📊 广告推送筛选条件: 所有用户")
            
            # 获取用户列表
            user_collection = self.config.get_agent_user_collection()
            users = list(user_collection.find(query, {'user_id': 1}))
            
            total_users = len(users)
            logger.info(f"📢 准备广播广告到 {total_users} 个用户")
            
            if total_users == 0:
                logger.info("⚠️ 没有符合条件的用户，跳过广播")
                return 0
            
            # 限制最大发送数量
            max_recipients = self.config.AGENT_AD_DM_MAX_PER_RUN
            if max_recipients > 0 and total_users > max_recipients:
                users = users[:max_recipients]
                logger.info(f"⚠️ 受 AGENT_AD_DM_MAX_PER_RUN 限制，只发送给前 {max_recipients} 个用户")
            
            # 逐个发送
            success_count = 0
            bot = Bot(self.config.BOT_TOKEN)
            
            for idx, user in enumerate(users, 1):
                user_id = user.get('user_id')
                if not user_id:
                    continue
                
                try:
                    bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode=parse_mode
                    )
                    success_count += 1
                    
                    if idx % 50 == 0:
                        logger.info(f"📤 已发送 {idx}/{len(users)} 条广告消息")
                    
                    # 添加小延迟避免触发 Telegram 限流
                    time.sleep(0.05)
                    
                except Exception as user_err:
                    # 单个用户发送失败不影响其他用户
                    logger.warning(f"⚠️ 向用户 {user_id} 发送广告失败: {user_err}")
                    continue
            
            logger.info(f"✅ 广告推送完成: 成功 {success_count}/{len(users)} 个用户")
            return success_count
            
        except Exception as e:
            logger.error(f"❌ 广告推送失败: {e}")
            traceback.print_exc()
            return 0

    def auto_sync_new_products(self):
        """自动同步总部新增商品到代理（增强版：支持价格为0的商品预建记录 + 统一协议号分类）"""
        try:
            all_products = list(self.config.ejfl.find({}))
            synced = 0
            updated = 0
            activated = 0
            unified = 0  # 统一分类计数
            
            for p in all_products:
                nowuid = p.get('nowuid')
                if not nowuid:
                    continue
                
                # ✅ 检查商品是否已存在于代理价格表
                exists = self.config.agent_product_prices.find_one({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'original_nowuid': nowuid
                })
                
                # ✅ 安全获取总部价格（处理异常情况）
                original_price = self._safe_price(p.get('money'))
                
                # ✅ 分类检测：使用新的双协议号分类逻辑
                leixing = p.get('leixing')
                projectname = p.get('projectname', '')
                
                if self.config.AGENT_CLONE_HEADQUARTERS_CATEGORIES:
                    # HQ克隆模式：使用新的协议号双分类逻辑
                    protocol_category = self._classify_protocol_subcategory(projectname, leixing)
                    if protocol_category:
                        # 是协议号类商品，使用分类后的结果（主或老）
                        category = protocol_category
                    else:
                        # 非协议号商品，保持原始分类名
                        category = leixing
                else:
                    # 传统模式：只统一协议号别名，其它分类保持原样
                    if leixing is None or leixing in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES:
                        category = self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED
                    else:
                        category = leixing  # 保持原始分类名
                
                if not exists:
                    # ✅ 新商品：创建代理价格记录，使用默认加价
                    agent_markup = self.config.AGENT_DEFAULT_MARKUP
                    agent_price = round(original_price + agent_markup, 2)
                    
                    # ✅ 即使总部价为0也创建记录，但标记为未激活
                    is_active = original_price > 0
                    needs_price_set = original_price <= 0
                    
                    self.config.agent_product_prices.insert_one({
                        'agent_bot_id': self.config.AGENT_BOT_ID,
                        'original_nowuid': nowuid,
                        'agent_markup': agent_markup,
                        'agent_price': agent_price,
                        'original_price_snapshot': original_price,
                        'product_name': p.get('projectname', ''),
                        'category': category,  # ✅ 使用检测后的分类
                        'is_active': is_active,
                        'needs_price_set': needs_price_set,
                        'auto_created': True,
                        'sync_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'created_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    synced += 1
                    # 统计协议号分类（主分类或老分类）
                    if category in [self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME, self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME, self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]:
                        unified += 1
                    status_msg = "待补价" if needs_price_set else "已激活"
                    logger.info(f"✅ 新增同步商品: {p.get('projectname')} (nowuid: {nowuid}, 总部价: {original_price}U, 代理价: {agent_price}U, 状态: {status_msg}, 分类: {category})")
                else:
                    # ✅ 已存在的商品：更新商品名称、分类和价格
                    updates = {}
                    if exists.get('product_name') != p.get('projectname'):
                        updates['product_name'] = p.get('projectname', '')
                    
                    # ✅ 更新分类（包括将旧的协议号分类迁移到新的双分类）
                    old_category = exists.get('category')
                    if old_category != category:
                        updates['category'] = category
                        # 统计协议号分类（主分类或老分类）
                        if category in [self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME, self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME, self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]:
                            unified += 1
                    
                    # ✅ 更新总部价格快照
                    if abs(exists.get('original_price_snapshot', 0) - original_price) > 0.01:
                        updates['original_price_snapshot'] = original_price
                    
                    # ✅ 重新计算代理价格（总部价 + 加价）
                    agent_markup = float(exists.get('agent_markup', 0))
                    new_agent_price = round(original_price + agent_markup, 2)
                    if abs(exists.get('agent_price', 0) - new_agent_price) > 0.01:
                        updates['agent_price'] = new_agent_price
                    
                    # ✅ 如果之前是待补价状态，现在总部价>0，自动激活
                    if exists.get('needs_price_set') and original_price > 0:
                        updates['is_active'] = True
                        updates['needs_price_set'] = False
                        activated += 1
                        logger.info(f"✅ 自动激活商品: {p.get('projectname')} (总部价已补: {original_price}U)")
                    
                    if updates:
                        updates['sync_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        updates['updated_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        self.config.agent_product_prices.update_one(
                            {'agent_bot_id': self.config.AGENT_BOT_ID, 'original_nowuid': nowuid},
                            {'$set': updates}
                        )
                        updated += 1
            
            # ✅ 处理旧数据：将已存在的协议号类商品重新分类到主/老分类
            if self.config.AGENT_CLONE_HEADQUARTERS_CATEGORIES:
                # HQ克隆模式下，重新分类所有协议号类商品
                old_protocol_categories = [
                    self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED,
                    *self.config.AGENT_PROTOCOL_CATEGORY_ALIASES,
                    None
                ]
                
                # 查找所有可能是协议号类的记录
                protocol_records = self.config.agent_product_prices.find({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'category': {'$in': old_protocol_categories}
                })
                
                for old_rec in protocol_records:
                    nowuid = old_rec.get('original_nowuid')
                    if not nowuid:
                        continue
                    
                    # 获取总部商品信息
                    hq_product = self.config.ejfl.find_one({'nowuid': nowuid})
                    if not hq_product:
                        continue
                    
                    product_name = hq_product.get('projectname', '')
                    leixing = hq_product.get('leixing')
                    
                    # 重新分类
                    new_category = self._classify_protocol_subcategory(product_name, leixing)
                    if not new_category:
                        # 如果不是协议号类，保持原leixing
                        new_category = leixing
                    
                    old_cat = old_rec.get('category')
                    if old_cat != new_category and new_category:
                        result = self.config.agent_product_prices.update_one(
                            {'_id': old_rec['_id']},
                            {'$set': {
                                'category': new_category,
                                'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }}
                        )
                        if result.modified_count > 0:
                            unified += 1
                            updated += 1
                            logger.info(f"✅ 迁移商品分类: {product_name} ({old_cat} -> {new_category})")
            else:
                # 传统模式：将旧别名统一到AGENT_PROTOCOL_CATEGORY_UNIFIED
                old_aliases_to_unify = [alias for alias in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES if alias != self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]
                old_aliases_to_unify.append(None)  # 包含 None
                
                # 查找所有需要统一的旧记录
                old_records = self.config.agent_product_prices.find({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'category': {'$in': old_aliases_to_unify}
                })
                
                for old_rec in old_records:
                    old_cat = old_rec.get('category')
                    if old_cat != self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
                        result = self.config.agent_product_prices.update_one(
                            {'_id': old_rec['_id']},
                            {'$set': {
                                'category': self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED,
                                'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }}
                        )
                        if result.modified_count > 0:
                            unified += 1
                            updated += 1
            
            if synced > 0 or updated > 0 or activated > 0 or unified > 0:
                logger.info(f"✅ 商品同步完成: 新增 {synced} 个, 更新 {updated} 个, 激活 {activated} 个, Unified protocol category: {unified} items")
            
            return synced
        except Exception as e:
            logger.error(f"❌ 自动同步失败: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def get_product_categories(self) -> List[Dict]:
        """获取商品分类列表（一级分类）- HQ克隆模式 + 容错回退"""
        try:
            # ✅ 每次获取分类时自动同步新商品
            self.auto_sync_new_products()
            
            # ========== HQ克隆模式：严格按照总部fenlei顺序显示 ==========
            if self.config.AGENT_CLONE_HEADQUARTERS_CATEGORIES:
                try:
                    logger.info("🔄 使用HQ克隆模式构建分类列表...")
                    
                    # 步骤1：从总部 fenlei 表读取分类（保持顺序）
                    fenlei_docs = list(self.config.fenlei.find({}).sort('_id', 1))
                    fenlei_categories = [doc.get('projectname') for doc in fenlei_docs if doc.get('projectname')]
                    
                    if not fenlei_categories:
                        logger.warning("⚠️ HQ fenlei表为空，回退到传统模式")
                        raise Exception("HQ fenlei empty, fallback")
                    
                    # 步骤2：读取所有HQ商品的leixing和projectname，用于智能分类
                    all_hq_products = list(self.config.ejfl.find({}, {'nowuid': 1, 'leixing': 1, 'projectname': 1}))
                    hq_product_map = {p['nowuid']: p for p in all_hq_products if p.get('nowuid')}
                    
                    # 步骤3：读取代理端已激活的商品
                    agent_products = list(self.config.agent_product_prices.find({
                        'agent_bot_id': self.config.AGENT_BOT_ID,
                        'is_active': True
                    }, {'original_nowuid': 1}))
                    
                    active_nowuids = [p['original_nowuid'] for p in agent_products if p.get('original_nowuid')]
                    
                    # 步骤4：根据智能检测，将每个商品归入对应分类
                    category_products = {}  # {category_name: set(nowuids)}
                    
                    # 初始化所有fenlei分类
                    for cat in fenlei_categories:
                        category_products[cat] = set()
                    
                    # 初始化双协议号分类（主分类和老号分类）
                    category_products[self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME] = set()
                    category_products[self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME] = set()
                    
                    # 将激活的商品按智能检测规则归入分类
                    for nowuid in active_nowuids:
                        hq_prod = hq_product_map.get(nowuid)
                        if not hq_prod:
                            continue
                        
                        leixing = hq_prod.get('leixing')
                        projectname = hq_prod.get('projectname', '')
                        
                        # 使用新的协议号双分类逻辑
                        protocol_category = self._classify_protocol_subcategory(projectname, leixing)
                        if protocol_category:
                            # 是协议号类商品，归入对应的协议号分类（主或老）
                            category_products[protocol_category].add(nowuid)
                        elif leixing and leixing in category_products:
                            # 如果leixing在fenlei中，归入对应分类
                            category_products[leixing].add(nowuid)
                        elif leixing:
                            # 如果leixing不在fenlei中，创建动态分类
                            if leixing not in category_products:
                                category_products[leixing] = set()
                            category_products[leixing].add(nowuid)
                        else:
                            # 如果leixing为空，归入主协议号分类（兜底）
                            category_products[self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME].add(nowuid)
                    
                    # 步骤5：统计每个分类的库存
                    category_stock = {}
                    for cat_name, nowuid_set in category_products.items():
                        if nowuid_set:
                            stock = self.config.hb.count_documents({
                                'nowuid': {'$in': list(nowuid_set)},
                                'state': 0
                            })
                            category_stock[cat_name] = stock
                        else:
                            category_stock[cat_name] = 0
                    
                    # 步骤6：按照HQ fenlei顺序构建结果，并在指定位置插入双协议号分类
                    result = []
                    protocol_inserted = False
                    insert_index = self.config.HQ_PROTOCOL_CATEGORY_INDEX - 1  # 转为0-based索引
                    
                    for i, cat in enumerate(fenlei_categories):
                        # 在指定位置插入双协议号分类（主分类和老号分类）
                        if i == insert_index and not protocol_inserted:
                            # 先插入主协议号分类
                            main_cat = self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME
                            main_stock = category_stock.get(main_cat, 0)
                            main_count = len(category_products.get(main_cat, set()))
                            if main_stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                                result.append({
                                    '_id': main_cat,
                                    'stock': main_stock,
                                    'count': main_count
                                })
                            
                            # 紧接着插入老号协议分类
                            old_cat = self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME
                            old_stock = category_stock.get(old_cat, 0)
                            old_count = len(category_products.get(old_cat, set()))
                            if old_stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                                result.append({
                                    '_id': old_cat,
                                    'stock': old_stock,
                                    'count': old_count
                                })
                            
                            protocol_inserted = True
                        
                        # 添加当前fenlei分类（跳过协议号分类本身，避免重复）
                        if cat not in [self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME, 
                                      self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME,
                                      self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]:
                            stock = category_stock.get(cat, 0)
                            count = len(category_products.get(cat, set()))
                            if stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                                result.append({
                                    '_id': cat,
                                    'stock': stock,
                                    'count': count
                                })
                    
                    # 如果索引超出范围，在末尾追加双协议号分类
                    if not protocol_inserted:
                        # 主协议号分类
                        main_cat = self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME
                        main_stock = category_stock.get(main_cat, 0)
                        main_count = len(category_products.get(main_cat, set()))
                        if main_stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                            result.append({
                                '_id': main_cat,
                                'stock': main_stock,
                                'count': main_count
                            })
                        
                        # 老号协议分类
                        old_cat = self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME
                        old_stock = category_stock.get(old_cat, 0)
                        old_count = len(category_products.get(old_cat, set()))
                        if old_stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                            result.append({
                                '_id': old_cat,
                                'stock': old_stock,
                                'count': old_count
                            })
                    
                    # 添加动态分类（不在fenlei中的分类，排在后面）
                    for cat_name in category_products.keys():
                        if (cat_name not in fenlei_categories and 
                            cat_name not in [self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME, 
                                           self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME,
                                           self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]):
                            stock = category_stock.get(cat_name, 0)
                            count = len(category_products.get(cat_name, set()))
                            if stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                                result.append({
                                    '_id': cat_name,
                                    'stock': stock,
                                    'count': count
                                })
                    
                    main_count = len(category_products.get(self.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME, set()))
                    old_count = len(category_products.get(self.config.HQ_PROTOCOL_OLD_CATEGORY_NAME, set()))
                    logger.info(f"✅ HQ克隆模式：共 {len(result)} 个分类，主协议号 {main_count} 个商品，老协议号 {old_count} 个商品")
                    return result
                    
                except Exception as hq_clone_err:
                    logger.error(f"❌ HQ克隆模式失败，回退到传统模式: {hq_clone_err}")
                    import traceback
                    traceback.print_exc()
                    # 继续执行传统模式
            
            # ========== 传统模式：基于agent_product_prices聚合 ==========
            logger.info("🔄 使用传统模式构建分类列表...")
            
            # 步骤1：读取总部 fenlei 表的一级分类名称
            fenlei_categories = []
            try:
                fenlei_docs = list(self.config.fenlei.find({}, {'projectname': 1}))
                fenlei_categories = [doc.get('projectname') for doc in fenlei_docs if doc.get('projectname')]
                logger.info(f"✅ 从总部 fenlei 表读取到 {len(fenlei_categories)} 个分类")
            except Exception as fenlei_err:
                logger.warning(f"⚠️ 读取总部 fenlei 表失败（将回退到 agent_product_prices 聚合）: {fenlei_err}")
            
            # 步骤2：读取代理端已激活商品及其分类
            agent_products = list(self.config.agent_product_prices.find({
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'is_active': True
            }, {'original_nowuid': 1, 'category': 1}))
            
            # 步骤3：构建分类名集合及其 nowuid 映射
            categories_map = {}  # {category_name: {'nowuids': set(), 'stock': int}}
            
            # 3.1 先从 fenlei 分类初始化（保持原始名称，不做统一映射）
            for cat in fenlei_categories:
                if cat and cat not in categories_map:
                    categories_map[cat] = {'nowuids': set(), 'stock': 0}
            
            # 3.2 确保统一协议号分类存在于分类映射中
            if self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED not in categories_map:
                categories_map[self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED] = {'nowuids': set(), 'stock': 0}
            
            # 3.3 收集代理端已激活商品的 nowuid 到对应分类
            for prod in agent_products:
                nowuid = prod.get('original_nowuid')
                if not nowuid:
                    continue
                
                raw_category = prod.get('category')
                
                # ✅ 检查是否为协议号别名：如果是，归入统一协议号分类
                if raw_category is None or raw_category in self.config.AGENT_PROTOCOL_CATEGORY_ALIASES or raw_category == self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
                    # 归入统一协议号分类
                    categories_map[self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED]['nowuids'].add(nowuid)
                else:
                    # 其它分类：直接使用原始分类名（不做统一映射）
                    if raw_category not in categories_map:
                        # 如果该分类不在 fenlei 中，也添加进来（动态分类）
                        categories_map[raw_category] = {'nowuids': set(), 'stock': 0}
                    categories_map[raw_category]['nowuids'].add(nowuid)
            
            # 步骤4：统计每个分类的库存
            for cat_name, cat_data in categories_map.items():
                nowuid_set = cat_data['nowuids']
                if nowuid_set:
                    # 统计这些 nowuid 在 hb 表中 state=0 的数量
                    stock = self.config.hb.count_documents({
                        'nowuid': {'$in': list(nowuid_set)},
                        'state': 0
                    })
                    cat_data['stock'] = stock
                else:
                    cat_data['stock'] = 0
            
            # 步骤5：根据配置决定是否显示零库存分类
            result = []
            for cat_name, cat_data in categories_map.items():
                stock = cat_data['stock']
                nowuid_count = len(cat_data['nowuids'])
                
                # 根据配置决定是否包含零库存分类
                if stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                    result.append({
                        '_id': cat_name,
                        'stock': stock,
                        'count': nowuid_count
                    })
            
            # 步骤6：按库存降序排序（零库存的在后面）
            result.sort(key=lambda x: -x['stock'])
            
            # 步骤7：容错检查
            if not result:
                logger.warning("⚠️ 未获取到任何分类，可能 fenlei 为空且无已激活商品")
                return []
            
            logger.info(f"✅ 获取商品分类成功（传统模式）: 共 {len(result)} 个分类，其中统一协议号分类包含 {len(categories_map.get(self.config.AGENT_PROTOCOL_CATEGORY_UNIFIED, {}).get('nowuids', set()))} 个商品")
            return result
            
        except Exception as e:
            logger.error(f"❌ 获取商品分类失败: {e}")
            import traceback
            traceback.print_exc()
            
            # ========== 容错回退：基于 agent_product_prices 的动态聚合 ==========
            try:
                logger.info("🔄 尝试回退到基于 agent_product_prices 的动态聚合...")
                
                agent_products = list(self.config.agent_product_prices.find({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'is_active': True
                }, {'original_nowuid': 1, 'category': 1}))
                
                fallback_map = {}
                for prod in agent_products:
                    nowuid = prod.get('original_nowuid')
                    if not nowuid:
                        continue
                    
                    raw_cat = prod.get('category')
                    unified_cat = self._unify_category(raw_cat)
                    
                    if unified_cat not in fallback_map:
                        fallback_map[unified_cat] = set()
                    fallback_map[unified_cat].add(nowuid)
                
                fallback_result = []
                for cat_name, nowuid_set in fallback_map.items():
                    stock = self.config.hb.count_documents({
                        'nowuid': {'$in': list(nowuid_set)},
                        'state': 0
                    })
                    if stock > 0 or self.config.AGENT_SHOW_EMPTY_CATEGORIES:
                        fallback_result.append({
                            '_id': cat_name,
                            'stock': stock,
                            'count': len(nowuid_set)
                        })
                
                fallback_result.sort(key=lambda x: -x['stock'])
                logger.info(f"✅ 回退聚合成功: {len(fallback_result)} 个分类")
                return fallback_result
                
            except Exception as fallback_err:
                logger.error(f"❌ 回退聚合也失败: {fallback_err}")
                return []

    def get_products_by_category(self, category: str, page: int = 1, limit: int = 10) -> Dict:
        try:
            skip = (page - 1) * limit
            
            # ✅ 处理统一协议号分类查询
            if category == AGENT_PROTOCOL_CATEGORY_UNIFIED:
                # 查询所有协议号类商品（leixing 为 None/空/'协议号'/'未分类'）
                match_condition = {
                    '$or': [
                        {'leixing': None}, 
                        {'leixing': ''}, 
                        {'leixing': '协议号'},
                        {'leixing': '未分类'}
                    ]
                }
            # ✅ 兼容旧的协议号/未分类查询（也查统一分类）
            elif category in ['协议号', '未分类']:
                match_condition = {
                    '$or': [
                        {'leixing': None}, 
                        {'leixing': ''}, 
                        {'leixing': '协议号'},
                        {'leixing': '未分类'}
                    ]
                }
            else:
                match_condition = {'leixing': category}
            
            pipeline = [
                {'$match': match_condition},
                {'$lookup': {
                    'from': 'agent_product_prices',
                    'localField': 'nowuid',
                    'foreignField': 'original_nowuid',
                    'as': 'agent_price'
                }},
                {'$match': {
                    'agent_price.agent_bot_id': self.config.AGENT_BOT_ID,
                    'agent_price.is_active': True
                }},
                {'$skip': skip},
                {'$limit': limit}
            ]
            products = list(self.config.ejfl.aggregate(pipeline))
            
            # ✅ 统计总数时也要用同样的条件
            if category == AGENT_PROTOCOL_CATEGORY_UNIFIED or category in ['协议号', '未分类']:
                total = self.config.ejfl.count_documents({
                    '$or': [
                        {'leixing': None}, 
                        {'leixing': ''}, 
                        {'leixing': '协议号'},
                        {'leixing': '未分类'}
                    ]
                })
            else:
                total = self.config.ejfl.count_documents({'leixing': category})
            
            return {
                'products': products,
                'total': total,
                'current_page': page,
                'total_pages': (total + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"❌ 获取分类商品失败: {e}")
            return {'products': [], 'total': 0, 'current_page': 1, 'total_pages': 0}

    def get_product_stock(self, nowuid: str) -> int:
        try:
            return self.config.hb.count_documents({'nowuid': nowuid, 'state': 0})
        except Exception as e:
            logger.error(f"❌ 获取库存失败: {e}")
            return 0

    def get_product_price(self, nowuid: str) -> Optional[float]:
        try:
            # 获取商品的总部价格（实时）
            origin = self.config.ejfl.find_one({'nowuid': nowuid})
            if not origin:
                return None
            original_price = float(origin.get('money', 0.0))
            
            # 获取代理设置的加价标记
            doc = self.config.agent_product_prices.find_one({
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'original_nowuid': nowuid,
                'is_active': True
            })
            if not doc:
                return None
            
            agent_markup = float(doc.get('agent_markup', 0.0))
            
            # ✅ 实时计算：代理价 = 总部价 + 加价
            agent_price = round(original_price + agent_markup, 2)
            return agent_price
        except Exception as e:
            logger.error(f"❌ 获取价格失败: {e}")
            return None

    def get_agent_product_list(self, user_id: int, page: int = 1, limit: int = 10) -> Dict:
        try:
            skip = (page - 1) * limit
            pipeline = [
                {'$lookup': {
                    'from': 'ejfl',
                    'localField': 'original_nowuid',
                    'foreignField': 'nowuid',
                    'as': 'product_info'
                }},
                {'$match': {
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'product_info': {'$ne': []}
                }},
                {'$skip': skip},
                {'$limit': limit}
            ]
            products = list(self.config.agent_product_prices.aggregate(pipeline))
            total = self.config.agent_product_prices.count_documents({'agent_bot_id': self.config.AGENT_BOT_ID})
            return {
                'products': products,
                'total': total,
                'current_page': page,
                'total_pages': (total + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"❌ 获取代理商品失败: {e}")
            return {'products': [], 'total': 0, 'current_page': 1, 'total_pages': 0}

    def update_agent_price(self, product_nowuid: str, new_agent_price: float) -> Tuple[bool, str]:
        try:
            origin = self.config.ejfl.find_one({'nowuid': product_nowuid})
            if not origin:
                return False, "原始商品不存在"
            
            # ✅ 获取实时总部价格
            op = float(origin.get('money', 0))
            
            # ✅ 计算新的加价标记
            new_markup = round(new_agent_price - op, 2)
            
            if new_markup < 0:
                return False, f"代理价格不能低于总部价格 {op} USDT（当前总部价），您输入的 {new_agent_price} USDT 低于总部价"
            
            # ✅ 保存加价标记和代理价格
            res = self.config.agent_product_prices.update_one(
                {'agent_bot_id': self.config.AGENT_BOT_ID, 'original_nowuid': product_nowuid},
                {'$set': {
                    'agent_markup': new_markup,
                    'agent_price': new_agent_price,  # ✅ 同时更新代理价格
                    'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'manual_updated': True
                }}
            )
            if res.modified_count:
                profit_rate = (new_markup / op * 100) if op else 0
                return True, f"价格更新成功！加价 {new_markup:.2f}U，利润率 {profit_rate:.1f}%（基于当前总部价 {op}U）"
            return False, "无变化"
        except Exception as e:
            logger.error(f"❌ 更新代理价格失败: {e}")
            return False, f"失败: {e}"

    def toggle_product_status(self, product_nowuid: str) -> Tuple[bool, str]:
        try:
            cur = self.config.agent_product_prices.find_one({
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'original_nowuid': product_nowuid
            })
            if not cur:
                return False, "商品不存在"
            new_status = not cur.get('is_active', True)
            self.config.agent_product_prices.update_one(
                {'agent_bot_id': self.config.AGENT_BOT_ID, 'original_nowuid': product_nowuid},
                {'$set': {'is_active': new_status, 'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}
            )
            return True, ("商品已启用" if new_status else "商品已禁用")
        except Exception as e:
            logger.error(f"❌ 切换状态失败: {e}")
            return False, f"失败: {e}"

    # ---------- 利润账户 ----------
    def update_profit_account(self, profit_delta: float):
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            acc = self.config.agent_profit_account.find_one({'agent_bot_id': self.config.AGENT_BOT_ID})
            if not acc:
                self.config.agent_profit_account.insert_one({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'total_profit': round(profit_delta, 6),
                    'withdrawn_profit': 0.0,
                    'created_time': now,
                    'updated_time': now
                })
            else:
                self.config.agent_profit_account.update_one(
                    {'agent_bot_id': self.config.AGENT_BOT_ID},
                    {'$inc': {'total_profit': round(profit_delta, 6)},
                     '$set': {'updated_time': now}}
                )
        except Exception as e:
            logger.error(f"❌ 更新利润账户失败: {e}")

    def get_profit_summary(self) -> Dict:
        try:
            acc = self.config.agent_profit_account.find_one({'agent_bot_id': self.config.AGENT_BOT_ID}) or {}
            total_profit = float(acc.get('total_profit', 0.0))
            q_base = {
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'apply_role': 'agent',
                'type': 'agent_profit_withdrawal'
            }
            coll = self.config.withdrawal_requests

            def sum_status(st: str):
                return sum([float(x.get('amount', 0)) for x in coll.find({**q_base, 'status': st})])

            pending_amount = sum_status('pending')
            approved_amount = sum_status('approved')
            completed_amount = sum_status('completed')
            rejected_amount = sum_status('rejected')

            available_profit = total_profit - completed_amount - pending_amount - approved_amount
            if available_profit < 0:
                available_profit = 0.0

            if float(acc.get('withdrawn_profit', 0)) != completed_amount:
                self.config.agent_profit_account.update_one(
                    {'agent_bot_id': self.config.AGENT_BOT_ID},
                    {'$set': {'withdrawn_profit': round(completed_amount, 6),
                              'updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}},
                    upsert=True
                )

            return {
                'total_profit': round(total_profit, 6),
                'withdrawn_profit': round(completed_amount, 6),
                'pending_profit': round(pending_amount, 6),
                'approved_unpaid_profit': round(approved_amount, 6),
                'rejected_profit': round(rejected_amount, 6),
                'available_profit': round(available_profit, 6),
                'request_count_pending': coll.count_documents({**q_base, 'status': 'pending'}),
                'request_count_approved': coll.count_documents({**q_base, 'status': 'approved'}),
                'updated_time': acc.get('updated_time')
            }
        except Exception as e:
            logger.error(f"❌ 获取利润汇总失败: {e}")
            return {
                'total_profit': 0.0, 'withdrawn_profit': 0.0,
                'pending_profit': 0.0, 'approved_unpaid_profit': 0.0,
                'rejected_profit': 0.0, 'available_profit': 0.0,
                'request_count_pending': 0, 'request_count_approved': 0,
                'updated_time': None
            }

    def request_profit_withdrawal(self, user_id: int, amount: float, withdrawal_address: str) -> Tuple[bool, str]:
        try:
            if not self.config.is_admin(user_id):
                return False, "无权限"
            if amount <= 0:
                return False, "金额需大于0"
            summary = self.get_profit_summary()
            if amount > summary['available_profit']:
                return False, f"超过可提现余额 {summary['available_profit']:.2f} USDT"

            now = datetime.now()
            doc = {
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'user_id': user_id,
                'amount': round(amount, 6),
                'withdrawal_address': withdrawal_address,
                'status': 'pending',
                'created_time': now,
                'updated_time': now,
                'apply_role': 'agent',
                'type': 'agent_profit_withdrawal',
                'profit_snapshot': summary['available_profit'],
                # ✅ 添加代理通知配置快照
                'agent_notify_chat_id': self.config.AGENT_NOTIFY_CHAT_ID,
                'agent_bot_token': self.config.BOT_TOKEN
            }
            self.config.withdrawal_requests.insert_one(doc)

            if self.config.AGENT_NOTIFY_CHAT_ID:  # ✅ 正确
                try:
                    Bot(self.config.BOT_TOKEN).send_message(
                        chat_id=self.config.AGENT_NOTIFY_CHAT_ID,  # ✅ 修复：使用实例配置
                        text=(f"📢 <b>代理提现申请</b>\n\n"
                              f"🏢 代理ID：<code>{self._h(self.config.AGENT_BOT_ID)}</code>\n"
                              f"👤 用户：{self._link_user(user_id)}\n"
                              f"💰 金额：<b>{amount:.2f} USDT</b>\n"
                              f"🏦 地址：<code>{self._h(withdrawal_address)}</code>\n"
                              f"⏰ 时间：{now.strftime('%Y-%m-%d %H:%M:%S')}"),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as ne:
                    logger.warning(f"总部通知发送失败: {ne}")

            return True, "提现申请已提交，等待审核"
        except Exception as e:
            logger.error(f"❌ 提交提现失败: {e}")
            return False, "系统异常"

    # ---------- 充值创建 ----------
    def _gen_unique_suffix(self, digits: int = 4) -> int:
        return random.randint(1, 10**digits - 1)

    def _compose_expected_amount(self, base_amount: Decimal, suffix: int) -> Decimal:
        suffix_dec = Decimal(suffix) / Decimal(10**4)
        expected = (base_amount.quantize(Decimal("0.01")) + suffix_dec).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        return expected

    def create_recharge_order(self, user_id: int, base_amount: Decimal) -> Tuple[bool, str, Optional[Dict]]:
        try:
            if not self.config.AGENT_USDT_ADDRESS:
                return False, "系统地址未配置", None
            if base_amount < self.config.RECHARGE_MIN_USDT:
                return False, f"最低充值金额为 {self.config.RECHARGE_MIN_USDT} USDT", None

            for _ in range(5):
                code = self._gen_unique_suffix()
                expected_amount = self._compose_expected_amount(base_amount, code)
                exists = self.config.recharge_orders.find_one({
                    'agent_bot_id': self.config.AGENT_BOT_ID,
                    'status': {'$in': ['pending', 'created']},
                    'expected_amount': float(expected_amount),
                    'address': self.config.AGENT_USDT_ADDRESS
                })
                if not exists:
                    break
            else:
                return False, "系统繁忙，请稍后重试", None

            now = datetime.utcnow()
            expire_at = now + timedelta(minutes=self.config.RECHARGE_EXPIRE_MINUTES)
            order = {
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'user_id': user_id,
                'network': 'TRON',
                'token': self.config.TOKEN_SYMBOL,
                'address': self.config.AGENT_USDT_ADDRESS,
                'base_amount': float(base_amount),
                'expected_amount': float(expected_amount),
                'unique_code': code,
                'status': 'pending',
                'created_time': now,
                'expire_time': expire_at,
                'paid_time': None,
                'tx_id': None,
                'from_address': None,
                'confirmations': 0
            }
            ins = self.config.recharge_orders.insert_one(order)
            order['_id'] = ins.inserted_id
            return True, "创建成功", order
        except Exception as e:
            logger.error(f"❌ 创建充值订单失败: {e}")
            return False, "系统异常，请稍后再试", None

    # ---------- 纯二维码 + caption ----------
    def _build_plain_qr(self, order: Dict) -> Optional[BytesIO]:
        """生成仅包含地址的二维码"""
        if qrcode is None or Image is None:
            return None
        address = str(order.get('address') or '').strip()
        payload = address
        logger.info(f"[QR] encoding pure address: {payload}")
        qr = qrcode.QRCode(version=None, box_size=10, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        pad = 40
        W = img.size[0] + pad * 2
        H = img.size[1] + pad * 2
        canvas = Image.new("RGB", (W, H), (255, 255, 255))
        canvas.paste(img, (pad, pad))
        bio = BytesIO()
        canvas.save(bio, format="PNG")
        bio.seek(0)
        return bio

    def _send_recharge_text_fallback(self, chat_id: int, order: Dict, reply_markup: InlineKeyboardMarkup):
        expected_amt = Decimal(str(order['expected_amount'])).quantize(Decimal("0.0001"))
        base_amt = Decimal(str(order['base_amount'])).quantize(Decimal("0.01"))
        expire_bj = self._to_beijing(order.get('expire_time')).strftime('%Y-%m-%d %H:%M')
        text = (
            "💰 余额充值（自动到账）\n\n"
            f"网络: TRON-TRC20\n"
            f"代币: {self._h(self.config.TOKEN_SYMBOL)}\n"
            f"收款地址: <code>{self._h(order['address'])}</code>\n\n"
            "请按以下“识别金额”精确转账:\n"
            f"应付金额: <b>{expected_amt}</b> USDT\n"
            f"基础金额: {base_amt} USDT\n"
            f"识别码: {order['unique_code']}\n\n"
            f"有效期至: {expire_bj} （10分钟内未支付该订单失效）\n\n"
            "注意:\n"
            "• 必须精确到 4 位小数的“应付金额”\n"
            "• 系统自动监听入账，无需手动校验"
        )
        Bot(self.config.BOT_TOKEN).send_message(
            chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

    def send_plain_qr_with_caption(self, chat_id: int, order: Dict, reply_markup: InlineKeyboardMarkup):
        try:
            bio = self._build_plain_qr(order)
            expected_amt = Decimal(str(order['expected_amount'])).quantize(Decimal("0.0001"))
            base_amt = Decimal(str(order['base_amount'])).quantize(Decimal("0.01"))
            expire_bj = self._to_beijing(order.get('expire_time')).strftime('%Y-%m-%d %H:%M')
            caption = (
                "💰 <b>余额充值（自动到账）</b>\n\n"
                f"网络: TRON-TRC20\n"
                f"代币: {self._h(self.config.TOKEN_SYMBOL)}\n"
                f"收款地址: <code>{self._h(order['address'])}</code>\n\n"
                "请按以下“识别金额”精确转账:\n"
                f"应付金额: <b>{expected_amt}</b> USDT\n"
                f"基础金额: {base_amt} USDT\n"
                f"识别码: {order['unique_code']}\n\n"
                f"有效期至: {expire_bj} （10分钟内未支付该订单失效）\n\n"
                "注意:\n"
                "• 必须精确到 4 位小数的“应付金额”\n"
                "• 系统自动监听入账，无需手动校验"
            )
            if bio:
                Bot(self.config.BOT_TOKEN).send_photo(
                    chat_id=chat_id,
                    photo=bio,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            else:
                self._send_recharge_text_fallback(chat_id, order, reply_markup)
        except Exception as e:
            logger.warning(f"发送二维码caption失败: {e}")
            self._send_recharge_text_fallback(chat_id, order, reply_markup)

    # ---------- Tron 交易抓取与解析 ----------
    def _fetch_tronscan_transfers(self, to_address: str, limit: int = 50) -> List[Dict]:
        try:
            bases = [
                self.config.TRONSCAN_TRX20_API,
                "https://apilist.tronscanapi.com/api/token_trc20/transfers",
                "https://apilist.tronscan.org/api/token_trc20/transfers",
            ]
            tried = set()
            for base in bases:
                if not base or base in tried:
                    continue
                tried.add(base)
                params = {
                    "toAddress": to_address,
                    "contract": self.config.USDT_TRON_CONTRACT,
                    "contract_address": self.config.USDT_TRON_CONTRACT,
                    "limit": min(int(limit), 200),
                    "sort": "-timestamp",
                }
                try:
                    r = requests.get(base, params=params, timeout=10)
                    if r.status_code != 200:
                        logger.warning(f"TronScan API 非 200: {r.status_code} url={base}")
                        continue
                    data = r.json() or {}
                    items = data.get("token_transfers") or data.get("data") or []
                    return items
                except Exception as ie:
                    logger.warning(f"TronScan 调用异常 url={base}: {ie}")
                    continue
            return []
        except Exception as e:
            logger.warning(f"TronScan API 调用失败: {e}")
            return []

    def _fetch_trongrid_trc20_transfers(self, to_address: str, limit: int = 50) -> List[Dict]:
        try:
            base = self.config.TRONGRID_API_BASE
            url = f"{base}/v1/accounts/{to_address}/transactions/trc20"
            params = {
                "limit": min(int(limit), 200),
                "contract_address": self.config.USDT_TRON_CONTRACT
            }
            attempts = max(len(self.config.TRON_API_KEYS), 1)
            last_err = None
            for _ in range(attempts):
                headers = {}
                api_key = self.config._next_tron_api_key()
                if api_key:
                    headers[self.config.TRON_API_KEY_HEADER] = api_key
                try:
                    r = requests.get(url, params=params, headers=headers, timeout=10)
                    if r.status_code != 200:
                        last_err = f"HTTP {r.status_code}"
                        if r.status_code in (429, 500, 502, 503, 504):
                            continue
                        return []
                    data = r.json() or {}
                    items = data.get("data") or []
                    norm = []
                    for it in items:
                        to_addr = (it.get("to") or "").lower()
                        if to_addr != to_address.lower():
                            continue
                        token_info = it.get("token_info") or {}
                        dec = int(token_info.get("decimals") or 6)
                        raw_val = it.get("value")
                        amount_str = None
                        if raw_val is not None:
                            try:
                                amount_str = (Decimal(str(raw_val)) / Decimal(10 ** dec)).quantize(Decimal("0.0001"))
                            except Exception:
                                amount_str = None
                        norm.append({
                            "to_address": it.get("to"),
                            "from_address": it.get("from"),
                            "amount_str": str(amount_str) if amount_str is not None else None,
                            "block_ts": it.get("block_timestamp"),
                            "transaction_id": it.get("transaction_id"),
                            "tokenInfo": {"tokenDecimal": dec}
                        })
                    return norm
                except Exception as e:
                    last_err = str(e)
                    continue
            if last_err:
                logger.warning(f"TronGrid 查询失败（已轮换密钥）：{last_err}")
            return []
        except Exception as e:
            logger.warning(f"TronGrid API 异常: {e}")
            return []

    def _fetch_token_transfers(self, to_address: str, limit: int = 50) -> List[Dict]:
        items = []
        if getattr(self.config, "TRON_API_KEYS", None):
            items = self._fetch_trongrid_trc20_transfers(to_address, limit)
        if not items:
            items = self._fetch_tronscan_transfers(to_address, limit)
        return items

    def _parse_amount(self, it) -> Optional[Decimal]:
        try:
            if it.get("amount_str") is not None:
                return Decimal(str(it["amount_str"])).quantize(Decimal("0.0001"))
            token_info = it.get("tokenInfo") or it.get("token_info") or {}
            dec_raw = token_info.get("tokenDecimal") or token_info.get("decimals") or it.get("tokenDecimal")
            try:
                decimals = int(dec_raw) if dec_raw is not None else 6
            except Exception:
                decimals = 6
            for key in ("value", "amount", "quant", "value_str", "amount_value", "amountValue"):
                if it.get(key) is not None:
                    v = it.get(key)
                    dv = Decimal(str(v))
                    if (isinstance(v, int) or (isinstance(v, str) and v.isdigit())) and len(str(v)) > 12:
                        dv = dv / Decimal(10 ** decimals)
                    return dv.quantize(Decimal("0.0001"))
            return None
        except Exception:
            return None

    # ---------- 充值校验 / 入账 / 轮询 ----------
    def verify_recharge_order(self, order: Dict) -> Tuple[bool, str]:
        try:
            if order.get('status') != 'pending':
                return False, "订单状态不可校验"
            if datetime.utcnow() > order.get('expire_time', datetime.utcnow()):
                self.config.recharge_orders.update_one({'_id': order['_id']}, {'$set': {'status': 'expired'}})
                return False, "订单已过期"

            expected = Decimal(str(order['expected_amount'])).quantize(Decimal("0.0001"))
            address = order['address']
            transfers = self._fetch_token_transfers(address, limit=100)
            if not transfers:
                return False, "未查询到转账记录"

            created_ts = order['created_time']
            for it in transfers:
                to_addr = (it.get('to_address') or it.get('to') or it.get('transferToAddress') or '').lower()
                amt = self._parse_amount(it)
                ts_ms = it.get('block_ts') or it.get('timestamp') or 0
                tx_time = datetime.utcfromtimestamp(int(ts_ms) / 1000) if ts_ms else None
                if to_addr != address.lower():
                    continue
                if amt is None or amt != expected:
                    continue
                if not tx_time or tx_time < created_ts - timedelta(minutes=5):
                    continue
                tx_id = it.get('transaction_id') or it.get('hash') or it.get('txHash') or ''
                from_addr = it.get('from_address') or it.get('from') or ''
                self._settle_recharge(order, tx_id, from_addr, tx_time)
                return True, "充值成功自动入账"
            return False, "暂未匹配到您的转账"
        except Exception as e:
            logger.error(f"❌ 校验充值失败: {e}")
            return False, "校验异常，请稍后重试"

    def _settle_recharge(self, order: Dict, tx_id: str, from_addr: str, paid_time: datetime):
        try:
            self.config.recharge_orders.update_one(
                {'_id': order['_id'], 'status': 'pending'},
                {'$set': {
                    'status': 'paid',
                    'tx_id': tx_id,
                    'from_address': from_addr,
                    'paid_time': paid_time
                }}
            )
            amt = float(order['base_amount'])
            self.config.get_agent_user_collection().update_one(
                {'user_id': order['user_id']},
                {'$inc': {'USDT': amt},
                 '$set': {'last_active': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}
            )
            user_doc = self.config.get_agent_user_collection().find_one(
                {'user_id': order['user_id']}, {'USDT': 1}
            )
            new_balance = float(user_doc.get('USDT', 0.0)) if user_doc else 0.0

            # 用户通知
            try:
                bot = Bot(self.config.BOT_TOKEN)
                friendly_time = self._to_beijing(paid_time).strftime('%Y-%m-%d %H:%M:%S')
                tx_short = (tx_id[:12] + '...') if tx_id and len(tx_id) > 12 else (tx_id or '-')
                msg = (
                    "🎉 恭喜您，充值成功！\n"
                    f"充值金额：{amt:.2f} {self.config.TOKEN_SYMBOL}\n"
                    f"当前余额：{new_balance:.2f} {self.config.TOKEN_SYMBOL}\n"
                    f"当前时间：{friendly_time}\n"
                    f"交易：{tx_short}\n\n"
                    "🔥祝您生意兴隆，财源广进！"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛍️ 商品中心", callback_data="products"),
                     InlineKeyboardButton("👤 个人中心", callback_data="profile")],
                    [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list")]
                ])
                bot.send_message(chat_id=order['user_id'], text=msg, reply_markup=kb)
            except Exception as ue:
                logger.warning(f"用户充值成功通知发送失败: {ue}")

            # 群通知
            if self.config.AGENT_NOTIFY_CHAT_ID:  # ✅ 正确
                try:
                    tx_short = (tx_id[:12] + '...') if tx_id and len(tx_id) > 12 else (tx_id or '-')
                    text = (
                        "✅ <b>充值入账</b>\n\n"
                        f"🏢 代理ID：<code>{self._h(self.config.AGENT_BOT_ID)}</code>\n"
                        f"👤 用户：{self._link_user(order['user_id'])}\n"
                        f"💰 金额：<b>{amt:.2f} {self._h(self.config.TOKEN_SYMBOL)}</b>\n"
                        f"🏦 收款地址：<code>{self._h(self.config.AGENT_USDT_ADDRESS)}</code>\n"
                        f"🔗 TX：<code>{self._h(tx_short)}</code>"
                    )
                    Bot(self.config.BOT_TOKEN).send_message(
                        chat_id=self.config.AGENT_NOTIFY_CHAT_ID,  # ✅ 修复：使用实例配置
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=self._kb_tx_addr_user(tx_id, self.config.AGENT_USDT_ADDRESS, order['user_id'])
                    )
                except Exception as ne:
                    logger.warning(f"总部通知发送失败: {ne}")
        except Exception as e:
            logger.error(f"❌ 入账失败: {e}")

    def poll_and_auto_settle_recharges(self, max_orders: int = 80):
        try:
            now = datetime.utcnow()
            q = {
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'status': 'pending',
                'expire_time': {'$gte': now}
            }
            orders = list(self.config.recharge_orders.find(q).sort('created_time', -1).limit(max_orders))
            for od in orders:
                ok, _ = self.verify_recharge_order(od)
                if ok:
                    logger.info(f"充值自动入账成功 order={od.get('_id')}")
        except Exception as e:
            logger.warning(f"自动轮询充值异常: {e}")

    def list_recharges(self, user_id: int, limit: int = 10, include_canceled: bool = False) -> List[Dict]:
        try:
            q = {'agent_bot_id': self.config.AGENT_BOT_ID, 'user_id': user_id}
            if not include_canceled:
                q['status'] = {'$ne': 'canceled'}
            return list(self.config.recharge_orders.find(q).sort('created_time', -1).limit(limit))
        except Exception as e:
            logger.error(f"❌ 查询充值记录失败: {e}")
            return []

    def send_batch_files_to_user(self, user_id: int, items: List[Dict], product_name: str, order_id: str = "") -> int:
        logger.info(f"开始打包发送: {product_name} items={len(items)}")
        try:
            if not items:
                return 0
            bot = Bot(self.config.BOT_TOKEN)
            first = items[0]
            item_type = first.get('leixing', '')
            nowuid = first.get('nowuid', '')
            if item_type == '协议号':
                base_dir = f"{self.config.FILE_BASE_PATH}/协议号/{nowuid}"
            else:
                base_dir = f"{self.config.FILE_BASE_PATH}/{item_type}/{nowuid}"
            if not os.path.exists(base_dir):
                return 0
            delivery_dir = f"{self.config.FILE_BASE_PATH}/协议号发货"
            os.makedirs(delivery_dir, exist_ok=True)
            
            # ✅ 改成：日期_用户ID_订单号后4位.zip
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            short_order_id = order_id[-4:] if order_id else "0000"
            zip_filename = f"{date_str}_{user_id}_{short_order_id}.zip"
            zip_path = f"{delivery_dir}/{zip_filename}"
            
            files_added = 0
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    if item_type == '协议号':
                        for it in items:
                            pname = it.get('projectname', '')
                            jf = os.path.join(base_dir, f"{pname}.json")
                            sf = os.path.join(base_dir, f"{pname}.session")
                            if os.path.exists(jf):
                                zf.write(jf, f"{pname}.json"); files_added += 1
                            if os.path.exists(sf):
                                zf.write(sf, f"{pname}.session"); files_added += 1
                        for fn in os.listdir(base_dir):
                            if fn.lower().endswith(('.txt', '.md')) and files_added < 500:
                                fp = os.path.join(base_dir, fn)
                                if os.path.isfile(fp):
                                    zf.write(fp, fn); files_added += 1
                    else:
                        for idx, _ in enumerate(items, 1):
                            for fn in os.listdir(base_dir):
                                fp = os.path.join(base_dir, fn)
                                if os.path.isfile(fp):
                                    zf.write(fp, f"{idx:02d}_{fn}")
                                    files_added += 1
                if files_added == 0:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    return 0
                if os.path.getsize(zip_path) > 50 * 1024 * 1024:
                    os.remove(zip_path)
                    return 0
                with open(zip_path, 'rb') as f:
                    bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=(f"📁 <b>{self._h(product_name)}</b>\n"
                                # f"📦 批量发货文件包\n"
                                 f"🔢 商品数量: {len(items)} 个\n"
                                # f"📂 文件总数: {files_added} 个\n"
                                 f"⏰ 发货时间: {self._to_beijing(datetime.utcnow()).strftime('%Y-%m-%d %H:%M:%S')}"),
                        parse_mode=ParseMode.HTML
                    )
                try:
                    os.remove(zip_path)
                except:
                    pass
                return 1
            except Exception as e:
                logger.error(f"打包失败: {e}")
                try:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                except:
                    pass
                return 0
        except Exception as e:
            logger.error(f"批量发送失败: {e}")
            return 0

    # ---------- 购买流程 ----------
    def process_purchase(self, user_id: int, product_nowuid: str, quantity: int = 1) -> Tuple[bool, Any]:
        try:
            coll_users = self.config.get_agent_user_collection()
            user = coll_users.find_one({'user_id': user_id})
            if not user:
                return False, "用户不存在"

            # ✅ 获取商品原始信息
            product = self.config.ejfl.find_one({'nowuid': product_nowuid})
            if not product:
                return False, "原始商品不存在"

            # ✅ 获取代理价格配置
            price_cfg = self.config.agent_product_prices.find_one({
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'original_nowuid': product_nowuid,
                'is_active': True
            })
            if not price_cfg:
                return False, "商品不存在或已下架"

            # ✅ 获取库存
            items = list(self.config.hb.find({'nowuid': product_nowuid, 'state': 0}).limit(quantity))
            if len(items) < quantity:
                return False, "库存不足"

            # ✅ 实时计算代理价格
            origin_price = float(product.get('money', 0))
            agent_markup = float(price_cfg.get('agent_markup', 0))
            agent_price = round(origin_price + agent_markup, 2)

            total_cost = agent_price * quantity
            balance = float(user.get('USDT', 0))

            if balance < total_cost:
                return False, "余额不足"

            # ✅ 记录扣款前余额
            before_balance = balance
            
            new_balance = balance - total_cost
            coll_users.update_one(
                {'user_id': user_id},
                {'$set': {'USDT': new_balance, 'last_active': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
                 '$inc': {'zgje': total_cost, 'zgsl': quantity}}
            )
            
            # ✅ 扣款后获取更新后的用户信息（用于统计）
            user_after = coll_users.find_one({'user_id': user_id})
            after_balance = float(user_after.get('USDT', 0))
            total_spent_after = float(user_after.get('zgje', 0))
            total_orders_after = int(user_after.get('zgsl', 0))
            avg_order_value = round(total_spent_after / max(total_orders_after, 1), 2)

            ids = [i['_id'] for i in items]
            sale_time = self._to_beijing(datetime.utcnow()).strftime('%Y-%m-%d %H:%M:%S')
            self.config.hb.update_many(
                {'_id': {'$in': ids}},
                {'$set': {'state': 1, 'sale_time': sale_time, 'yssj': sale_time, 'gmid': user_id}}
            )

            # ✅ 订单号先生成
            order_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{user_id}"

            files_sent = 0
            try:
                # ✅ 发货函数传递订单号当作第4参数
                files_sent = self.send_batch_files_to_user(user_id, items, product.get('projectname', ''), order_id)
            except Exception as fe:
                logger.warning(f"发货文件异常: {fe}")

            # ✅ 计算利润
            profit_unit = max(agent_markup, 0)
            total_profit = profit_unit * quantity
            if total_profit > 0:
                self.update_profit_account(total_profit)

            order_coll = self.config.get_agent_gmjlu_collection()
            order_coll.insert_one({
                'leixing': 'purchase',
                'bianhao': order_id,
                'user_id': user_id,
                'projectname': product.get('projectname', ''),
                'nowuid': product_nowuid,  # ✅ 添加nowuid以支持重新下载
                'text': str(ids[0]) if ids else '',
                'ts': total_cost,
                'timer': sale_time,
                'count': quantity,
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'original_price': origin_price,
                'agent_price': agent_price,
                'profit_per_unit': profit_unit,
                'total_profit': total_profit,
                # ✅ 新增字段用于可靠的重新下载
                'item_ids': ids,  # 所有已售出商品的 ObjectId 列表
                'first_item_id': str(ids[0]) if ids else '',  # 第一个商品ID（向后兼容/调试）
                'category': product.get('leixing', '')  # 商品分类
            })

            # ✅ 群通知（新版格式）
            try:
                if self.config.AGENT_NOTIFY_CHAT_ID:
                    # 计算所需变量
                    profit_per_unit = agent_markup
                    total_value = total_cost
                    
                    # 获取机器人用户名
                    bot_username = None
                    try:
                        bot = Bot(self.config.BOT_TOKEN)
                        bot_info = bot.get_me()
                        bot_username = bot_info.username
                    except Exception as e:
                        logger.warning(f"⚠️ 获取机器人用户名失败: {e}")
                    
                    # 构建新版通知文本
                    text = self.build_purchase_notify_text(
                        user_id=user_id,
                        product_name=product.get('projectname', ''),
                        category=price_cfg.get('category') or product.get('leixing') or '未分类',
                        nowuid=product_nowuid,
                        quantity=quantity,
                        profit_per_unit=profit_per_unit,
                        origin_price=origin_price,
                        agent_price=agent_price,
                        total_value=total_value,
                        total_profit=total_profit,
                        before_balance=before_balance,
                        after_balance=after_balance,
                        total_spent_after=total_spent_after,
                        total_orders_after=total_orders_after,
                        avg_order_value=avg_order_value,
                        sale_time_beijing=sale_time,
                        order_id=order_id,
                        bot_username=bot_username
                    )
                    
                    # 发送群通知
                    try:
                        Bot(self.config.BOT_TOKEN).send_message(
                            chat_id=self.config.AGENT_NOTIFY_CHAT_ID,
                            text=text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=self._kb_purchase_notify(product_nowuid, user_id)
                        )
                        logger.info(f"✅ 购买群通知发送成功: 订单 {order_id}")
                    except Exception as send_err:
                        logger.error(f"❌ 购买群通知发送失败: {send_err}")
                        # 尝试不使用HTML格式重新发送（回退方案）
                        try:
                            simple_text = (
                                f"🛒 用户购买通知\n\n"
                                f"订单号: {order_id}\n"
                                f"用户: {user_id}\n"
                                f"商品: {product.get('projectname', '')}\n"
                                f"数量: {quantity}\n"
                                f"总额: {total_cost:.2f}U\n"
                                f"利润: {total_profit:.2f}U"
                            )
                            Bot(self.config.BOT_TOKEN).send_message(
                                chat_id=self.config.AGENT_NOTIFY_CHAT_ID,
                                text=simple_text,
                                reply_markup=self._kb_purchase_notify(product_nowuid, user_id)
                            )
                            logger.info(f"✅ 购买群通知（简化版）发送成功: 订单 {order_id}")
                        except Exception as fallback_err:
                            logger.error(f"❌ 购买群通知回退方案也失败: {fallback_err}")
                            import traceback
                            traceback.print_exc()
                else:
                    logger.warning(f"⚠️ AGENT_NOTIFY_CHAT_ID 未配置，跳过群通知发送")
            except Exception as ne:
                logger.error(f"❌ 购买群通知处理异常: {ne}")
                import traceback
                traceback.print_exc()

            return True, {
                'order_id': order_id,
                'product_name': product.get('projectname', ''),
                'quantity': quantity,
                'total_cost': total_cost,
                'user_balance': new_balance,
                'files_sent': files_sent,
                'total_profit': total_profit
            }
        except Exception as e:
            logger.error(f"处理购买失败: {e}")
            return False, f"购买处理异常: {e}"
    
    def list_user_orders(self, user_id: int, page: int = 1, limit: int = 10) -> Dict:
        """
        获取用户的购买订单列表（分页）
        
        Args:
            user_id: 用户ID
            page: 页码（从1开始）
            limit: 每页数量
        
        Returns:
            Dict: {
                'orders': List[Dict],  # 订单列表
                'total': int,          # 总订单数
                'current_page': int,   # 当前页码
                'total_pages': int     # 总页数
            }
        """
        try:
            order_coll = self.config.get_agent_gmjlu_collection()
            
            # 查询条件
            query = {
                'leixing': 'purchase',
                'user_id': user_id
            }
            
            # 计算总数
            total = order_coll.count_documents(query)
            
            if total == 0:
                return {
                    'orders': [],
                    'total': 0,
                    'current_page': 1,
                    'total_pages': 0
                }
            
            # 计算分页
            skip = (page - 1) * limit
            total_pages = (total + limit - 1) // limit
            
            # 查询订单（按时间倒序）
            orders = list(order_coll.find(query).sort('timer', -1).skip(skip).limit(limit))
            
            return {
                'orders': orders,
                'total': total,
                'current_page': page,
                'total_pages': total_pages
            }
            
        except Exception as e:
            logger.error(f"❌ 获取用户订单列表失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                'orders': [],
                'total': 0,
                'current_page': 1,
                'total_pages': 0
            }
            
    # ---------- 统计 ----------
    def get_sales_statistics(self, days: int = 30) -> Dict:
        try:
            end = datetime.now(); start = end - timedelta(days=days)
            s_str = start.strftime('%Y-%m-%d %H:%M:%S')
            e_str = end.strftime('%Y-%m-%d %H:%M:%S')
            coll = self.config.get_agent_gmjlu_collection()
            base = list(coll.aggregate([
                {'$match': {'leixing': 'purchase', 'timer': {'$gte': s_str, '$lte': e_str}}},
                {'$group': {'_id': None, 'total_orders': {'$sum': 1},
                            'total_revenue': {'$sum': '$ts'}, 'total_quantity': {'$sum': '$count'}}}
            ]))
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
            today = list(coll.aggregate([
                {'$match': {'leixing': 'purchase', 'timer': {'$gte': today_start}}},
                {'$group': {'_id': None, 'today_orders': {'$sum': 1},
                            'today_revenue': {'$sum': '$ts'}, 'today_quantity': {'$sum': '$count'}}}
            ]))
            popular = list(coll.aggregate([
                {'$match': {'leixing': 'purchase', 'timer': {'$gte': s_str, '$lte': e_str}}},
                {'$group': {'_id': '$projectname', 'total_sold': {'$sum': '$count'},
                            'total_revenue': {'$sum': '$ts'}, 'order_count': {'$sum': 1}}},
                {'$sort': {'total_sold': -1}},
                {'$limit': 5}
            ]))
            result = {
                'period_days': days,
                'total_orders': base[0]['total_orders'] if base else 0,
                'total_revenue': base[0]['total_revenue'] if base else 0.0,
                'total_quantity': base[0]['total_quantity'] if base else 0,
                'today_orders': today[0]['today_orders'] if today else 0,
                'today_revenue': today[0]['today_revenue'] if today else 0.0,
                'today_quantity': today[0]['today_quantity'] if today else 0,
                'popular_products': popular,
                'avg_order_value': round((base[0]['total_revenue'] / max(base[0]['total_orders'], 1)), 2) if base else 0.0
            }
            return result
        except Exception as e:
            logger.error(f"❌ 销售统计失败: {e}")
            return {
                'period_days': days, 'total_orders': 0, 'total_revenue': 0.0, 'total_quantity': 0,
                'today_orders': 0, 'today_revenue': 0.0, 'today_quantity': 0,
                'popular_products': [], 'avg_order_value': 0.0
            }

    def get_user_statistics(self) -> Dict:
        try:
            users = self.config.get_agent_user_collection()
            total = users.count_documents({})
            active_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            active = users.count_documents({'last_active': {'$gte': active_date}})
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
            today_new = users.count_documents({'register_time': {'$gte': today_start}})
            bal_data = list(users.aggregate([{'$group': {
                '_id': None, 'total_balance': {'$sum': '$USDT'},
                'avg_balance': {'$avg': '$USDT'}, 'total_spent': {'$sum': '$zgje'}
            }}]))
            spending_levels = {
                'bronze': users.count_documents({'zgje': {'$lt': 50}}),
                'silver': users.count_documents({'zgje': {'$gte': 50, '$lt': 100}}),
                'gold': users.count_documents({'zgje': {'$gte': 100}})
            }
            return {
                'total_users': total,
                'active_users': active,
                'today_new_users': today_new,
                'total_balance': bal_data[0]['total_balance'] if bal_data else 0.0,
                'avg_balance': round(bal_data[0]['avg_balance'], 2) if bal_data else 0.0,
                'total_spent': bal_data[0]['total_spent'] if bal_data else 0.0,
                'spending_levels': spending_levels,
                'activity_rate': round((active / max(total, 1)) * 100, 1)
            }
        except Exception as e:
            logger.error(f"❌ 用户统计失败: {e}")
            return {
                'total_users': 0, 'active_users': 0, 'today_new_users': 0,
                'total_balance': 0.0, 'avg_balance': 0.0, 'total_spent': 0.0,
                'spending_levels': {'bronze': 0, 'silver': 0, 'gold': 0}, 'activity_rate': 0.0
            }

    def get_product_statistics(self) -> Dict:
        try:
            total = self.config.agent_product_prices.count_documents({'agent_bot_id': self.config.AGENT_BOT_ID})
            active = self.config.agent_product_prices.count_documents({'agent_bot_id': self.config.AGENT_BOT_ID, 'is_active': True})
            stock_pipeline = [
                {'$match': {'state': 0}},
                {'$group': {'_id': '$leixing', 'stock_count': {'$sum': 1}}},
                {'$sort': {'stock_count': -1}}
            ]
            stock_by_category = list(self.config.hb.aggregate(stock_pipeline))
            total_stock = self.config.hb.count_documents({'state': 0})
            sold_stock = self.config.hb.count_documents({'state': 1})
            price_stats = list(self.config.agent_product_prices.aggregate([
                {'$match': {'agent_bot_id': self.config.AGENT_BOT_ID}},
                {'$group': {'_id': None, 'avg_profit_rate': {'$avg': '$profit_rate'},
                            'highest_profit_rate': {'$max': '$profit_rate'},
                            'lowest_profit_rate': {'$min': '$profit_rate'}}}
            ]))
            return {
                'total_products': total,
                'active_products': active,
                'inactive_products': total - active,
                'total_stock': total_stock,
                'sold_stock': sold_stock,
                'stock_by_category': stock_by_category,
                'avg_profit_rate': round(price_stats[0]['avg_profit_rate'], 1) if price_stats else 0.0,
                'highest_profit_rate': round(price_stats[0]['highest_profit_rate'], 1) if price_stats else 0.0,
                'lowest_profit_rate': round(price_stats[0]['lowest_profit_rate'], 1) if price_stats else 0.0,
                'stock_turnover_rate': round((sold_stock / max(sold_stock + total_stock, 1)) * 100, 1)
            }
        except Exception as e:
            logger.error(f"❌ 商品统计失败: {e}")
            return {
                'total_products': 0, 'active_products': 0, 'inactive_products': 0,
                'total_stock': 0, 'sold_stock': 0, 'stock_by_category': [],
                'avg_profit_rate': 0.0, 'highest_profit_rate': 0.0,
                'lowest_profit_rate': 0.0, 'stock_turnover_rate': 0.0
            }

    def get_financial_statistics(self, days: int = 30) -> Dict:
        try:
            end = datetime.now(); start = end - timedelta(days=days)
            s_str = start.strftime('%Y-%m-%d %H:%M:%S')
            coll = self.config.get_agent_gmjlu_collection()
            revenue = list(coll.aggregate([
                {'$match': {'leixing': 'purchase', 'timer': {'$gte': s_str}}},
                {'$group': {'_id': None, 'total_revenue': {'$sum': '$ts'}, 'order_count': {'$sum': 1}}}
            ]))
            trends = list(coll.aggregate([
                {'$match': {'leixing': 'purchase', 'timer': {'$gte': (end - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')}}},
                {'$addFields': {'date_only': {'$substr': ['$timer', 0, 10]}}},
                {'$group': {'_id': '$date_only', 'daily_revenue': {'$sum': '$ts'}, 'daily_orders': {'$sum': 1}}},
                {'$sort': {'_id': 1}}
            ]))
            total_rev = revenue[0]['total_revenue'] if revenue else 0.0
            order_cnt = revenue[0]['order_count'] if revenue else 0
            return {
                'period_days': days,
                'total_revenue': total_rev,
                'estimated_profit': total_rev * 0.2,
                'profit_margin': 20.0,
                'order_count': order_cnt,
                'avg_order_value': round(total_rev / max(order_cnt, 1), 2),
                'daily_trends': trends,
                'revenue_growth': 0.0
            }
        except Exception as e:
            logger.error(f"❌ 财务统计失败: {e}")
            return {
                'period_days': days, 'total_revenue': 0.0, 'estimated_profit': 0.0,
                'profit_margin': 0.0, 'order_count': 0, 'avg_order_value': 0.0,
                'daily_trends': [], 'revenue_growth': 0.0
            }


class AgentBotHandlers:
    """按钮与消息处理"""

    def __init__(self, core: AgentBotCore):
        self.core = core
        self.user_states: Dict[int, Dict[str, Any]] = {}

    def H(self, s: Any) -> str:
        try:
            return html_escape(str(s) if s is not None else "", quote=False)
        except Exception:
            return str(s or "")


    def safe_edit_message(self, query, text, keyboard, parse_mode=ParseMode.HTML):
        markup, is_photo = None, False
        try:
            # 将普通二维数组按钮转为 InlineKeyboardMarkup
            markup = keyboard if isinstance(keyboard, InlineKeyboardMarkup) else InlineKeyboardMarkup(keyboard)

            # 图片消息（photo）没有 message.text，需要改用 edit_message_caption
            is_photo = bool(getattr(query.message, "photo", None)) and not getattr(query.message, "text", None)
            if is_photo:
                if len(text) > 1000:
                    text = text[:1000] + "..."
                query.edit_message_caption(caption=text, reply_markup=markup, parse_mode=parse_mode)
                return

            old_text = (getattr(query.message, "text", "") or "")
            if old_text.strip() == text.strip():
                try:
                    query.answer("界面已是最新状态")
                except:
                    pass
                return

            query.edit_message_text(text, reply_markup=markup, parse_mode=parse_mode)

        except Exception as e:
            msg = str(e)
            try:
                if "Message is not modified" in msg:
                    try:
                        query.answer("界面已是最新状态")
                    except:
                        pass
                elif "Can't parse entities" in msg or "can't parse entities" in msg:
                    # HTML 解析失败，回退纯文本
                    if is_photo:
                        query.edit_message_caption(caption=text, reply_markup=markup, parse_mode=None)
                    else:
                        query.edit_message_text(text, reply_markup=markup, parse_mode=None)
                    logger.warning(f"HTML解析失败，已回退纯文本发送: {e}")
                elif "There is no text in the message to edit" in msg or "no text in the message to edit" in msg:
                    # 照片消息/无法编辑文本，删除原消息并重发新文本
                    try:
                        chat_id = query.message.chat_id
                        query.message.delete()
                        Bot(self.core.config.BOT_TOKEN).send_message(
                            chat_id=chat_id, text=text, reply_markup=markup, parse_mode=parse_mode
                        )
                    except Exception as e_del:
                        logger.warning(f"回退删除重发失败: {e_del}")
                else:
                    logger.warning(f"⚠️ safe_edit_message 编辑失败: {e}")
                    try:
                        query.answer("刷新失败，请重试")
                    except:
                        pass
            except Exception:
                pass

    # ========== 命令 / 主菜单 ==========


    def start_command(self, update: Update, context: CallbackContext):
        user = update.effective_user
        
        # ✅ 解析深度链接参数（payload）
        payload = None
        if context.args and len(context.args) > 0:
            payload = context.args[0]
            logger.info(f"📥 收到深度链接启动: payload={payload}, user_id={user.id}")
        
        # ✅ 启动时触发一次商品同步（所有用户，确保商品列表是最新的）
        synced = self.core.auto_sync_new_products()
        if synced > 0:
            logger.info(f"✅ 启动时同步了 {synced} 个新商品")
        
        if self.core.register_user(user.id, user.username or "", user.first_name or ""):
            # ✅ 处理 restock 深度链接 - 直接显示商品分类（无欢迎消息）
            if payload == "restock":
                try:
                    uid = user.id
                    # 直接获取并显示商品分类
                    categories = self.core.get_product_categories()
                    
                    if not categories:
                        text = self.core.t(uid, 'products.categories.no_categories')
                        kb = [[InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")]]
                    else:
                        text = (
                            f"<b>{self.core.t(uid, 'products.categories.title')}</b>\n\n"
                            f"<b>{self.core.t(uid, 'products.categories.search_tip')}</b>\n\n"
                            f"<b>{self.core.t(uid, 'products.categories.first_purchase_tip')}</b>\n\n"
                            f"<b>{self.core.t(uid, 'products.categories.inactive_tip')}</b>"
                        )
                        
                        kb = []
                        unit = self.core.t(uid, 'common.unit')
                        for cat in categories:
                            button_text = f"{cat['_id']}  [{cat['stock']}{unit}]"
                            kb.append([InlineKeyboardButton(button_text, callback_data=f"category_{cat['_id']}")])
                        
                        kb.append([InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")])
                    
                    update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
                    logger.info(f"✅ 已为用户 {user.id} 直接显示商品分类")
                    return
                    
                except Exception as e:
                    logger.error(f"❌ 显示商品分类失败: {e}")
                    import traceback
                    traceback.print_exc()
                    uid = user.id
                    text = self.core.t(uid, 'error.load_failed')
                    kb = [[InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")]]
                    update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
                    return
            
            # ✅ 处理 product_<nowuid> 深度链接 - 直接显示商品购买页面
            if payload and payload.startswith("product_"):
                nowuid = payload.replace("product_", "")
                try:
                    uid = user.id
                    # 直接显示商品详情（购买页面）
                    prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
                    if not prod:
                        text = self.core.t(uid, 'products.not_exist')
                        kb = [[InlineKeyboardButton(self.core.t(uid, 'products.back_to_list'), callback_data="products")]]
                    else:
                        price = self.core.get_product_price(nowuid)
                        stock = self.core.get_product_stock(nowuid)
                        
                        if price is None:
                            text = self.core.t(uid, 'products.price_not_set')
                            kb = [[InlineKeyboardButton(self.core.t(uid, 'products.back_to_list'), callback_data="products")]]
                        else:
                            # ✅ 获取商品在代理价格表中的分类（统一后的分类）
                            agent_price_info = self.core.config.agent_product_prices.find_one({
                                'agent_bot_id': self.core.config.AGENT_BOT_ID,
                                'original_nowuid': nowuid
                            })
                            # 使用统一后的分类，如果没有则回退到原leixing
                            category = agent_price_info.get('category') if agent_price_info else (prod.get('leixing') or AGENT_PROTOCOL_CATEGORY_UNIFIED)
                            
                            # ✅ 完全按照总部的简洁格式
                            product_name = self.H(prod.get('projectname', 'N/A'))
                            unit = self.core.t(uid, 'common.unit')
                            
                            text = (
                                f"<b>{self.core.t(uid, 'products.purchase_status')} {product_name}\n\n</b>"
                                f"<b>{self.core.t(uid, 'products.price_label', price=price)}\n\n</b>"
                                f"<b>{self.core.t(uid, 'products.stock_label', stock=stock)}{unit}\n\n</b>"
                                f"<b>{self.core.t(uid, 'products.purchase_warning')}\n</b>"
                            )
                            
                            kb = []
                            if stock > 0:
                                kb.append([InlineKeyboardButton(self.core.t(uid, 'products.buy'), callback_data=f"buy_{nowuid}"),
                                          InlineKeyboardButton(self.core.t(uid, 'help.instructions'), callback_data="help")])
                            else:
                                text += f"\n\n{self.core.t(uid, 'products.out_of_stock')}"
                                kb.append([InlineKeyboardButton(self.core.t(uid, 'help.instructions_simple'), callback_data="help")])
                            
                            # ✅ 使用统一后的分类作为返回目标
                            kb.append([InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main"),
                                      InlineKeyboardButton(self.core.t(uid, 'common.back'), callback_data=f"category_{category}")])
                    
                    update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
                    logger.info(f"✅ 已为用户 {user.id} 直接显示商品 {nowuid} 购买页面")
                    return
                    
                except Exception as e:
                    logger.error(f"❌ 显示商品购买页面失败: {e}")
                    import traceback
                    traceback.print_exc()
                    uid = user.id
                    text = self.core.t(uid, 'error.load_failed')
                    kb = [[InlineKeyboardButton(self.core.t(uid, 'products.back_to_list'), callback_data="products")]]
                    update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
                    return
            
            # ✅ 默认启动消息
            uid = user.id
            username_display = self.H(user.username or self.core.t(uid, 'common.not_set'))
            nickname_display = self.H(user.first_name or self.core.t(uid, 'common.not_set'))
            
            text = f"""{self.core.t(uid, 'start.welcome', agent_name=self.H(self.core.config.AGENT_NAME))}

{self.core.t(uid, 'start.user_info')}
{self.core.t(uid, 'start.user_id', uid=user.id)}
{self.core.t(uid, 'start.username', username=username_display)}
{self.core.t(uid, 'start.nickname', nickname=nickname_display)}

{self.core.t(uid, 'start.select_function')}"""
            kb = [
                [InlineKeyboardButton(self.core.t(uid, 'btn.products'), callback_data="products"),
                 InlineKeyboardButton(self.core.t(uid, 'btn.profile'), callback_data="profile")],
                [InlineKeyboardButton(self.core.t(uid, 'btn.recharge'), callback_data="recharge"),
                 InlineKeyboardButton(self.core.t(uid, 'btn.orders'), callback_data="orders")]
            ]
            if self.core.config.is_admin(user.id):
                kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.price_management'), callback_data="price_management"),
                           InlineKeyboardButton(self.core.t(uid, 'btn.system_reports'), callback_data="system_reports")])
                kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.profit_center'), callback_data="profit_center")])
            kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.support'), callback_data="support"),
                       InlineKeyboardButton(self.core.t(uid, 'btn.help'), callback_data="help")])
            kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.language'), callback_data="language_menu")])
            update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        else:
            uid = user.id
            update.message.reply_text(self.core.t(uid, 'common.init_failed'))

    def show_main_menu(self, query):
        user = query.from_user
        uid = user.id
        kb = [
            [InlineKeyboardButton(self.core.t(uid, 'btn.products'), callback_data="products"),
             InlineKeyboardButton(self.core.t(uid, 'btn.profile'), callback_data="profile")],
            [InlineKeyboardButton(self.core.t(uid, 'btn.recharge'), callback_data="recharge"),
             InlineKeyboardButton(self.core.t(uid, 'btn.orders'), callback_data="orders")]
        ]
        if self.core.config.is_admin(user.id):
            kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.price_management'), callback_data="price_management"),
                       InlineKeyboardButton(self.core.t(uid, 'btn.system_reports'), callback_data="system_reports")])
            kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.profit_center'), callback_data="profit_center")])
        kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.support'), callback_data="support"),
                   InlineKeyboardButton(self.core.t(uid, 'btn.help'), callback_data="help")])
        kb.append([InlineKeyboardButton(self.core.t(uid, 'btn.language'), callback_data="language_menu")])
        text = self.core.t(uid, 'main_menu.title') + "\n\n" + self.core.t(uid, 'main_menu.current_time', time=self.core._to_beijing(datetime.utcnow()).strftime('%Y-%m-%d %H:%M:%S'))
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def reload_admins_command(self, update: Update, context: CallbackContext):
        """重新加载管理员列表（仅管理员可用）"""
        user = update.effective_user
        
        # 检查是否为管理员
        if not self.core.config.is_admin(user.id):
            update.message.reply_text("❌ 无权限")
            return
        
        # 重新加载管理员列表
        admins = self.core.config.reload_admins()
        
        # 返回当前管理员列表
        if admins:
            admin_list = ", ".join(str(uid) for uid in admins)
            text = f"✅ 管理员列表已重新加载\n\n当前管理员用户ID:\n{admin_list}"
        else:
            text = "⚠️ 管理员列表已重新加载，但当前无管理员配置"
        
        update.message.reply_text(text)

    # ========== 利润中心 / 提现 ==========
    def show_profit_center(self, query):
        uid = query.from_user.id
        if not self.core.config.is_admin(uid):
            self.safe_edit_message(query, "❌ 无权限", [[InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]], parse_mode=None)
            return
        s = self.core.get_profit_summary()
        refresh_time = self.core._to_beijing(datetime.utcnow()).strftime('%Y-%m-%d %H:%M:%S')
        text = f"""💸 <b>利润中心</b>

累计利润: {s['total_profit']:.2f} USDT
已提现: {s['withdrawn_profit']:.2f} USDT
待审核: {s['pending_profit']:.2f} USDT
可提现: {s['available_profit']:.2f} USDT
待处理申请: {s['request_count_pending']} 笔


刷新时间: {refresh_time}

• 审核/付款需人工处理
"""
        kb = [
            [InlineKeyboardButton("📝 申请提现", callback_data="profit_withdraw"),
             InlineKeyboardButton("📋 申请记录", callback_data="profit_withdraw_list")],
            [InlineKeyboardButton("🔄 刷新", callback_data="profit_center"),
             InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=ParseMode.HTML)

    def start_withdrawal(self, query):
        uid = query.from_user.id
        if not self.core.config.is_admin(uid):
            query.answer("无权限", show_alert=True)
            return
        s = self.core.get_profit_summary()
        if s['available_profit'] <= 0:
            self.safe_edit_message(query, "⚠️ 当前无可提现利润", [[InlineKeyboardButton("🔙 返回", callback_data="profit_center")]], parse_mode=None)
            return
        text = f"""📝 <b>申请提现</b>

可提现金额: {s['available_profit']:.2f} USDT
请输入提现金额（例如: {min(s['available_profit'], 10):.2f}）

直接发送数字金额："""
        self.user_states[uid] = {'state': 'waiting_withdraw_amount'}
        self.safe_edit_message(query, text, [[InlineKeyboardButton("🔙 取消", callback_data="profit_center")]], parse_mode=ParseMode.HTML)

    def handle_withdraw_amount_input(self, update: Update):
        uid = update.effective_user.id
        text = update.message.text.strip()
        try:
            amt = float(text)
            s = self.core.get_profit_summary()
            if amt <= 0:
                update.message.reply_text("❌ 金额必须大于0，请重新输入")
                return
            if amt > s['available_profit']:
                update.message.reply_text(f"❌ 超出可提现余额 {s['available_profit']:.2f}，请重新输入")
                return
            self.user_states[uid] = {'state': 'waiting_withdraw_address', 'withdraw_amount': amt}
            update.message.reply_text(
                f"✅ 金额已记录：{amt:.2f} USDT\n请发送收款地址（TRON 或 ERC20）",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="profit_center")]])
            )
        except ValueError:
            update.message.reply_text("❌ 金额格式错误，请输入数字")

    def handle_withdraw_address_input(self, update: Update):
        uid = update.effective_user.id
        address = update.message.text.strip()
        if len(address) < 10:
            update.message.reply_text("❌ 地址长度不正确，请重新输入")
            return
        amt = self.user_states[uid]['withdraw_amount']
        ok, msg = self.core.request_profit_withdrawal(uid, amt, address)
        self.user_states.pop(uid, None)
        if ok:
            update.message.reply_text(
                f"✅ 提现申请成功\n金额：{amt:.2f} USDT\n地址：{self.H(address)}\n状态：待审核",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 返回利润中心", callback_data="profit_center")]]),
                parse_mode=ParseMode.HTML
            )
        else:
            update.message.reply_text(f"❌ {msg}")

    def show_withdrawal_list(self, query):
        uid = query.from_user.id
        if not self.core.config.is_admin(uid):
            self.safe_edit_message(query, "❌ 无权限", [[InlineKeyboardButton("返回", callback_data="back_main")]], parse_mode=None)
            return
        recs = self.core.config.withdrawal_requests.find({
            'agent_bot_id': self.core.config.AGENT_BOT_ID,
            'apply_role': 'agent',
            'type': 'agent_profit_withdrawal'
        }).sort('created_time', -1).limit(30)
        recs = list(recs)
        if not recs:
            self.safe_edit_message(query, "📋 提现记录\n\n暂无申请", [[InlineKeyboardButton("🔙 返回", callback_data="profit_center")]], parse_mode=None)
            return
        text = "📋 提现记录（最新优先）\n\n"
        for r in recs:
            status = r.get('status')
            amount = r.get('amount', 0.0)
            created = r.get('created_time')
            created_s = self.core._to_beijing(created).strftime('%m-%d %H:%M') if created else '-'
            addr = str(r.get('withdrawal_address', ''))
            addr_short = f"{addr[:6]}...{addr[-6:]}" if len(addr) > 12 else addr
            text += f"💰 {amount:.4f}U | {status}\n地址: {self.H(addr_short)} | 时间(京): {self.H(created_s)}\n"
            if status == 'rejected' and r.get('reject_reason'):
                text += f"原因: {self.H(r.get('reject_reason'))}\n"
            if status == 'completed' and r.get('tx_hash'):
                th = str(r['tx_hash'])
                text += f"Tx: {self.H(th[:12] + '...' if len(th) > 12 else th)}\n"
            text += "\n"
        text += "（需人工审核/付款）"
        self.safe_edit_message(query, text, [[InlineKeyboardButton("🔙 返回", callback_data="profit_center")]], parse_mode=None)

    # ========== 商品相关 ==========
    def show_product_categories(self, query):
        """显示商品分类（增强版：支持显示零库存分类）"""
        try:
            uid = query.from_user.id
            # ✅ 调用核心方法获取分类列表（包含零库存分类）
            categories = self.core.get_product_categories()
            
            if not categories:
                self.safe_edit_message(query, self.core.t(uid, 'products.categories.no_categories'), [[InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")]], parse_mode=None)
                return
            
            text = (
                f"<b>{self.core.t(uid, 'products.categories.title')}</b>\n\n"
                f"<b>{self.core.t(uid, 'products.categories.search_tip')}</b>\n\n"
                f"<b>{self.core.t(uid, 'products.categories.first_purchase_tip')}</b>\n\n"
                f"<b>{self.core.t(uid, 'products.categories.inactive_tip')}</b>"
            )
            
            kb = []
            unit = self.core.t(uid, 'common.unit')
            for cat in categories:
                button_text = f"{cat['_id']}  [{cat['stock']}{unit}]"
                kb.append([InlineKeyboardButton(button_text, callback_data=f"category_{cat['_id']}")])
            
            kb.append([InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")])
            
            self.safe_edit_message(query, text, kb, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"❌ 获取商品分类失败: {e}")
            import traceback
            traceback.print_exc()
            uid = query.from_user.id
            self.safe_edit_message(query, self.core.t(uid, 'error.load_failed'), [[InlineKeyboardButton(self.core.t(uid, 'common.back_main'), callback_data="back_main")]], parse_mode=None)
            
    def show_category_products(self, query, category: str, page: int = 1):
        """显示分类下的商品（二级分类）- 支持HQ克隆模式 + 统一协议号分类"""
        try:
            # ✅ 先自动同步新商品，确保最新商品能显示
            self.core.auto_sync_new_products()
            
            skip = (page - 1) * 10
            
            # ========== HQ克隆模式：直接查询ejfl并使用智能协议号检测 ==========
            if self.core.config.AGENT_CLONE_HEADQUARTERS_CATEGORIES:
                try:
                    # 查询ejfl中的所有商品（将根据leixing和projectname智能分类）
                    if category == self.core.config.HQ_PROTOCOL_MAIN_CATEGORY_NAME:
                        # 主协议号分类：协议号类但非老号
                        all_hq_products = list(self.core.config.ejfl.find({}, {
                            'nowuid': 1, 'projectname': 1, 'leixing': 1, 'money': 1
                        }))
                        
                        # 过滤出主协议号商品（协议号类但非老号）
                        main_protocol_nowuids = []
                        for p in all_hq_products:
                            leixing = p.get('leixing')
                            projectname = p.get('projectname', '')
                            if self.core._is_protocol_like(projectname, leixing) and not self.core._is_old_protocol(projectname):
                                main_protocol_nowuids.append(p['nowuid'])
                        
                        ejfl_match = {'nowuid': {'$in': main_protocol_nowuids}}
                        
                    elif category == self.core.config.HQ_PROTOCOL_OLD_CATEGORY_NAME:
                        # 老号协议分类：只包含老号协议
                        all_hq_products = list(self.core.config.ejfl.find({}, {
                            'nowuid': 1, 'projectname': 1, 'leixing': 1, 'money': 1
                        }))
                        
                        # 过滤出老号协议商品
                        old_protocol_nowuids = []
                        for p in all_hq_products:
                            leixing = p.get('leixing')
                            projectname = p.get('projectname', '')
                            if self.core._is_protocol_like(projectname, leixing) and self.core._is_old_protocol(projectname):
                                old_protocol_nowuids.append(p['nowuid'])
                        
                        ejfl_match = {'nowuid': {'$in': old_protocol_nowuids}}
                        
                    elif category == self.core.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
                        # 兼容旧的统一协议号分类（显示所有协议号）
                        all_hq_products = list(self.core.config.ejfl.find({}, {
                            'nowuid': 1, 'projectname': 1, 'leixing': 1, 'money': 1
                        }))
                        
                        protocol_nowuids = []
                        for p in all_hq_products:
                            leixing = p.get('leixing')
                            projectname = p.get('projectname', '')
                            if self.core._is_protocol_like(projectname, leixing):
                                protocol_nowuids.append(p['nowuid'])
                        
                        ejfl_match = {'nowuid': {'$in': protocol_nowuids}}
                        
                    else:
                        # 非协议号分类：精确匹配leixing（但排除协议号类商品）
                        candidate_products = list(self.core.config.ejfl.find({'leixing': category}, {
                            'nowuid': 1, 'projectname': 1, 'leixing': 1
                        }))
                        
                        # 过滤掉协议号类商品（它们应该在协议号分类中）
                        non_protocol_nowuids = []
                        for p in candidate_products:
                            leixing = p.get('leixing')
                            projectname = p.get('projectname', '')
                            if not self.core._is_protocol_like(projectname, leixing):
                                non_protocol_nowuids.append(p['nowuid'])
                        
                        ejfl_match = {'nowuid': {'$in': non_protocol_nowuids}}
                    
                    # 联合查询：ejfl + agent_product_prices + hb
                    pipeline = [
                        {'$match': ejfl_match},
                        {'$lookup': {
                            'from': 'agent_product_prices',
                            'localField': 'nowuid',
                            'foreignField': 'original_nowuid',
                            'as': 'agent_price'
                        }},
                        {'$match': {
                            'agent_price.agent_bot_id': self.core.config.AGENT_BOT_ID,
                            'agent_price.is_active': True
                        }},
                        {'$skip': skip},
                        {'$limit': 10}
                    ]
                    
                    products = list(self.core.config.ejfl.aggregate(pipeline))
                    
                    # 提取商品信息并计算库存和价格
                    products_with_stock = []
                    for p in products:
                        nowuid = p.get('nowuid')
                        if not nowuid:
                            continue
                        
                        # 获取库存
                        stock = self.core.get_product_stock(nowuid)
                        if stock <= 0:
                            continue
                        
                        # 获取价格
                        price = self.core.get_product_price(nowuid)
                        if price is None or price <= 0:
                            continue
                        
                        p['stock'] = stock
                        p['price'] = price
                        products_with_stock.append(p)
                    
                    # 按库存降序排列
                    products_with_stock.sort(key=lambda x: -x['stock'])
                    
                    logger.info(f"✅ HQ克隆模式：分类 '{category}' 获取到 {len(products_with_stock)} 个有库存商品")
                    
                except Exception as hq_err:
                    logger.error(f"❌ HQ克隆模式失败，回退到传统模式: {hq_err}")
                    import traceback
                    traceback.print_exc()
                    # 回退到传统模式（下面的代码）
                    products_with_stock = None
                
                # 如果HQ克隆模式成功，直接渲染
                if products_with_stock is not None:
                    text = (
                        "<b>🛒 这是商品列表  选择你需要的分类：</b>\n\n"
                        "❗️没使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！。\n\n"
                        "❗有密码的账户售后时间1小时内，二级未知的账户售后30分钟内！\n\n"
                        "❗购买后请第一时间检查账户，提供证明处理售后 超时损失自付！"
                    )
                    
                    kb = []
                    for p in products_with_stock:
                        name = p.get('projectname')
                        nowuid = p.get('nowuid')
                        price = p['price']
                        stock = p['stock']
                        
                        # ✅ 按钮格式
                        button_text = f"{name} {price}U   [{stock}个]"
                        kb.append([InlineKeyboardButton(button_text, callback_data=f"product_{nowuid}")])
                    
                    # 如果没有有库存的商品
                    if not kb:
                        kb.append([InlineKeyboardButton("暂无商品耐心等待", callback_data="no_action")])
                    
                    # ✅ 返回按钮
                    kb.append([
                        InlineKeyboardButton("🔙 返回", callback_data="back_products"),
                        InlineKeyboardButton("❌ 关闭", callback_data=f"close {query.from_user.id}")
                    ])
                    
                    self.safe_edit_message(query, text, kb, parse_mode='HTML')
                    return
            
            # ========== 传统模式：基于agent_product_prices分类 ==========
            logger.info(f"🔄 使用传统模式显示分类商品: {category}")
            
            # 判断是否为统一协议号分类
            if category == self.core.config.AGENT_PROTOCOL_CATEGORY_UNIFIED:
                # ✅ 统一协议号分类：匹配所有别名 + 统一分类名
                category_filter = {
                    'agent_bot_id': self.core.config.AGENT_BOT_ID,
                    'is_active': True,
                    '$or': [
                        {'category': {'$in': self.core.config.AGENT_PROTOCOL_CATEGORY_ALIASES}},
                        {'category': self.core.config.AGENT_PROTOCOL_CATEGORY_UNIFIED},
                        {'category': None}
                    ]
                }
            else:
                # ✅ 其它分类：精确匹配分类名
                category_filter = {
                    'agent_bot_id': self.core.config.AGENT_BOT_ID,
                    'category': category,
                    'is_active': True
                }
            
            # ✅ 查询该分类下代理激活的商品
            pipeline = [
                {'$match': category_filter},
                {'$lookup': {
                    'from': 'ejfl',
                    'localField': 'original_nowuid',
                    'foreignField': 'nowuid',
                    'as': 'product_info'
                }},
                {'$match': {
                    'product_info': {'$ne': []}
                }},
                {'$skip': skip},
                {'$limit': 10}
            ]
            
            price_docs = list(self.core.config.agent_product_prices.aggregate(pipeline))
            
            # ✅ 提取商品信息并计算库存和价格
            products_with_stock = []
            for pdoc in price_docs:
                if not pdoc.get('product_info'):
                    continue
                
                p = pdoc['product_info'][0]
                nowuid = p.get('nowuid')
                
                # 获取库存
                stock = self.core.get_product_stock(nowuid)
                if stock <= 0:
                    continue
                
                # 获取价格
                price = self.core.get_product_price(nowuid)
                if price is None or price <= 0:
                    continue
                
                p['stock'] = stock
                p['price'] = price
                products_with_stock.append(p)
            
            # 按库存降序排列
            products_with_stock.sort(key=lambda x: -x['stock'])
            
            # ✅ 文本格式
            text = (
                "<b>🛒 这是商品列表  选择你需要的分类：</b>\n\n"
                "❗️没使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！。\n\n"
                "❗有密码的账户售后时间1小时内，二级未知的账户售后30分钟内！\n\n"
                "❗购买后请第一时间检查账户，提供证明处理售后 超时损失自付！"
            )
            
            kb = []
            for p in products_with_stock:
                name = p.get('projectname')
                nowuid = p.get('nowuid')
                price = p['price']
                stock = p['stock']
                
                # ✅ 按钮格式
                button_text = f"{name} {price}U    [{stock}个]"
                kb.append([InlineKeyboardButton(button_text, callback_data=f"product_{nowuid}")])
            
            # 如果没有有库存的商品
            if not kb:
                kb.append([InlineKeyboardButton("暂无商品耐心等待", callback_data="no_action")])
            
            # ✅ 返回按钮
            kb.append([
                InlineKeyboardButton("🔙 返回", callback_data="back_products"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"close {query.from_user.id}")
            ])
            
            self.safe_edit_message(query, text, kb, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"❌ 获取分类商品失败: {e}")
            import traceback
            traceback.print_exc()
            self.safe_edit_message(query, "❌ 加载失败，请重试", [[InlineKeyboardButton("🔙 返回", callback_data="back_products")]], parse_mode=None)

    def show_product_detail(self, query, nowuid: str):
        """显示商品详情 - 完全仿照总部格式"""
        try:
            prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
            if not prod:
                self.safe_edit_message(query, "❌ 商品不存在", [[InlineKeyboardButton("🔙 返回", callback_data="back_products")]], parse_mode=None)
                return
            
            price = self.core.get_product_price(nowuid)
            stock = self.core.get_product_stock(nowuid)
            
            if price is None:
                self.safe_edit_message(query, "❌ 商品价格未设置", [[InlineKeyboardButton("🔙 返回", callback_data="back_products")]], parse_mode=None)
                return
            
            # ✅ 获取商品在代理价格表中的分类（统一后的分类）
            agent_price_info = self.core.config.agent_product_prices.find_one({
                'agent_bot_id': self.core.config.AGENT_BOT_ID,
                'original_nowuid': nowuid
            })
            # 使用统一后的分类，如果没有则回退到原leixing
            category = agent_price_info.get('category') if agent_price_info else (prod.get('leixing') or AGENT_PROTOCOL_CATEGORY_UNIFIED)
            
            # ✅ 完全按照总部的简洁格式
            product_name = self.H(prod.get('projectname', 'N/A'))
            product_status = "✅您正在购买："
            
            text = (
                f"<b>{product_status} {product_name}\n\n</b>"
                f"<b>💰 价格: {price:.2f} USDT\n\n</b>"
                f"<b>📦 库存: {stock}个\n\n</b>"
                f"<b>❗未使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！\n</b>"
                
            )
            
            kb = []
            if stock > 0:
                kb.append([InlineKeyboardButton("✅ 购买", callback_data=f"buy_{nowuid}"),
                          InlineKeyboardButton("❗使用说明", callback_data="help")])
            else:
                text += "\n\n⚠️ 商品缺货"
                kb.append([InlineKeyboardButton("使用说明", callback_data="help")])
            
            # ✅ 使用统一后的分类作为返回目标
            kb.append([InlineKeyboardButton("🏠 主菜单", callback_data="back_main"),
                      InlineKeyboardButton("返回", callback_data=f"category_{category}")])
            
            self.safe_edit_message(query, text, kb, parse_mode=ParseMode.HTML)
        
        except Exception as e:
            logger.error(f"❌ 获取商品详情失败: {e}")
            self.safe_edit_message(query, "❌ 加载失败，请重试", [[InlineKeyboardButton("🔙 返回", callback_data="back_products")]], parse_mode=None)
            
            
    def handle_buy_product(self, query, nowuid: str):
        """处理购买流程 - 完全仿照总部格式"""
        uid = query.from_user.id
        prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
        price = self.core.get_product_price(nowuid)
        stock = self.core.get_product_stock(nowuid)
        user = self.core.get_user_info(uid)
        bal = user.get('USDT', 0) if user else 0
        max_afford = int(bal // price) if price else 0
        max_qty = min(stock, max_afford)
        
        # ✅ 完全按照总部的格式
        text = (
            f"请输入数量:\n"
            f"格式: 10\n\n"
            f"✅ 您正在购买 - {self.H(prod['projectname'])}\n"
            f"💰 单价: {price} U\n"
            f"🪙 您的余额: {bal:.2f} U\n"
            f"📊 最多可买: {max_qty} 个"
        )
        kb = [
            [InlineKeyboardButton("❌ 取消交易", callback_data=f"product_{nowuid}")]
        ]
        
        # ✅ 保存当前消息的ID（这是要被删除的消息）
        input_msg_id = query.message.message_id
        
        # ✅ 修改消息显示"请输入数量"
        self.safe_edit_message(query, text, kb, parse_mode=None)
        
        # ✅ 保存消息 ID 到状态
        self.user_states[uid] = {
            'state': 'waiting_quantity',
            'product_nowuid': nowuid,
            'input_msg_id': input_msg_id  # ← 保存这条要被删除的消息ID
        }
        
        
    def handle_quantity_input(self, update: Update, context: CallbackContext):
        """处理购买数量输入 - 显示确认页面"""
        uid = update.effective_user.id
        if uid not in self.user_states or self.user_states[uid].get('state') != 'waiting_quantity':
            return
        
        try:
            qty = int(update.message.text.strip())
        except:
            update.message.reply_text("❌ 请输入有效整数")
            return
        
        st = self.user_states[uid]
        nowuid = st['product_nowuid']
        prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
        price = self.core.get_product_price(nowuid)
        stock = self.core.get_product_stock(nowuid)
        user = self.core.get_user_info(uid)
        bal = user.get('USDT', 0) if user else 0
        
        if qty <= 0:
            update.message.reply_text("❌ 数量需 > 0")
            return
        if qty > stock:
            update.message.reply_text(f"❌ 库存不足（当前 {stock}）")
            return
        
        total_cost = price * qty
        if total_cost > bal:
            update.message.reply_text(f"❌ 余额不足，需: {total_cost:.2f}U 当前: {bal:.2f}U")
            return
        
        chat_id = uid
        
        # ✅ 先删除"请输入数量"的消息
        if 'input_msg_id' in st:
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=st['input_msg_id'])
            except Exception as e:
                logger.error(f"删除输入数量消息失败: {e}")
        
        # ✅ 删除用户输入的数字消息
        try:
            update.message.delete()
        except Exception as e:
            logger.error(f"删除用户消息失败: {e}")
        
        # ✅ 显示确认页面（总部格式）
        text = (
            f"<b>✅ 您正在购买 - {self.H(prod['projectname'])}</b>\n\n"
            f"<b>🛍 数量: {qty}</b>\n\n"
            f"<b>💰 价格: {price}</b>\n\n"
            f"<b>🪙 您的余额: {bal:.2f}</b>"
        )
        
        kb = [
            [InlineKeyboardButton("❌ 取消交易", callback_data=f"product_{nowuid}"),
             InlineKeyboardButton("✅ 确认购买", callback_data=f"confirm_buy_{nowuid}_{qty}")],
            [InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]
        ]
        
        # ✅ 用 send_message 发送确认页面
        msg = context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )
        
        # ✅ 保存状态
        self.user_states[uid] = {
            'state': 'confirming_purchase',
            'product_nowuid': nowuid,
            'quantity': qty,
            'confirm_msg_id': msg.message_id  # 只需保存确认页面的ID
        }

    def handle_confirm_buy(self, query, nowuid: str, qty: int, context: CallbackContext):
        """确认购买 - 处理交易"""
        uid = query.from_user.id
        st = self.user_states.pop(uid, None)
        chat_id = query.message.chat_id
        
        # ✅ 删除确认页面的消息
        try:
            query.message.delete()
        except Exception as e:
            logger.error(f"删除确认页面失败: {e}")
        
        # 处理购买
        ok, res = self.core.process_purchase(uid, nowuid, qty)
        
        if ok:
            # ✅ 从环境变量加载通知模板内容
            custom_message_template = os.getenv("PURCHASE_SUCCESS_TEMPLATE", (
                "✅您的账户已打包完成，请查收！\n\n"
                "🔐二级密码:请在json文件中【two2fa】查看！\n\n"
                "⚠️注意：请马上检查账户，1小时内出现问题，联系客服处理！\n"
                "‼️超过售后时间，损失自付，无需多言！\n\n"
                "🔹 9号客服  @o9eth   @o7eth\n"
                "🔹 频道  @idclub9999\n"
                "🔹补货通知  @p5540"
            ))

            # ✅ 发送购买成功通知（不包括订单、商品等细节内容）
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍️ 继续购买", callback_data="products"),
                 InlineKeyboardButton("👤 个人中心", callback_data="profile")]
            ])
            try:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=os.getenv("PURCHASE_SUCCESS_TEMPLATE"),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                    )
                logger.info(f"✅ 自定义购买成功通知已发送给用户 {uid}")
            except Exception as msg_error:
                logger.error(f"❌ 发送购买成功通知失败: {msg_error}")
            
            query.answer("✅ 购买成功！")
        else:
            query.answer(f"❌ 购买失败: {res}", show_alert=True)
       
    def show_user_profile(self, query):
        """显示用户个人中心"""
        uid = query.from_user.id
        # 🔍 调试：打印查询的集合名和配置
        coll_name = f"agent_users_{self.core.config.AGENT_BOT_ID}"
        logger.info(f"🔍 DEBUG show_user_profile: uid={uid}, AGENT_BOT_ID={self.core.config.AGENT_BOT_ID}, collection={coll_name}")
    
        info = self.core.get_user_info(uid)
    
        # 🔍 调试：打印查询结果
        logger.info(f"🔍 DEBUG: query result for user {uid} = {info}")
        if not info:
            self.safe_edit_message(query, "❌ 用户信息不存在", [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]], parse_mode=None)
            return
        
        avg = round(info.get('zgje', 0) / max(info.get('zgsl', 1), 1), 2)
        level = '🥇 金牌' if info.get('zgje', 0) > 100 else '🥈 银牌' if info.get('zgje', 0) > 50 else '🥉 铜牌'
        
        text = (
            f"👤 个人中心\n\n"
            f"ID: {uid}\n"
            f"内部ID: {self.H(info.get('count_id', '-'))}\n"
            f"余额: {info.get('USDT', 0):.2f}U\n"
            f"累计消费: {info.get('zgje', 0):.2f}U  次数:{info.get('zgsl', 0)}\n"
            f"平均订单: {avg:.2f}U\n"
            f"等级: {level}\n"
        )
        
        kb = [
            [InlineKeyboardButton("💰 充值余额", callback_data="recharge"),
             InlineKeyboardButton("📊 订单历史", callback_data="orders")],
            [InlineKeyboardButton("🛍️ 商品中心", callback_data="products"),
             InlineKeyboardButton("📞 联系客服", callback_data="support")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ]
        
        self.safe_edit_message(query, text, kb, parse_mode=None)

    # ========== 充值 UI ==========
    def _format_recharge_text(self, order: Dict) -> str:
        base_amt = Decimal(str(order['base_amount'])).quantize(Decimal("0.01"))
        expected_amt = Decimal(str(order['expected_amount'])).quantize(Decimal("0.0001"))
        expire_bj = self.core._to_beijing(order.get('expire_time')).strftime('%Y-%m-%d %H:%M')
        return (
            "💰 余额充值（自动到账）\n\n"
            f"网络: TRON-TRC20\n"
            f"代币: {self.core.config.TOKEN_SYMBOL}\n"
            f"收款地址: <code>{self.H(order['address'])}</code>\n\n"
            "请按以下“识别金额”精确转账:\n"
            f"应付金额: <b>{expected_amt}</b> USDT\n"
            f"基础金额: {base_amt} USDT\n"
            f"识别码: {order['unique_code']}\n\n"
            f"有效期至: {expire_bj} （10分钟内未支付该订单失效）\n\n"
            "注意:\n"
            "• 必须精确到 4 位小数的“应付金额”\n"
            "• 系统自动监听入账，无需手动校验"
        )

    def show_recharge_options(self, query):
        uid = query.from_user.id
        text = ("💰 余额充值\n\n"
                "• 固定地址收款，自动到账\n"
                f"• 最低金额: {self.core.config.RECHARGE_MIN_USDT} USDT\n"
                f"• 有效期: 10分钟\n"
                f"• 轮询间隔: {self.core.config.RECHARGE_POLL_INTERVAL_SECONDS}s\n\n"
                "请选择金额或发送自定义金额（数字）：")
        kb = [
            [InlineKeyboardButton("10 USDT", callback_data="recharge_amount_10"),
             InlineKeyboardButton("30 USDT", callback_data="recharge_amount_30"),
             InlineKeyboardButton("50 USDT", callback_data="recharge_amount_50")],
            [InlineKeyboardButton("100 USDT", callback_data="recharge_amount_100"),
             InlineKeyboardButton("200 USDT", callback_data="recharge_amount_200"),
             InlineKeyboardButton("500 USDT", callback_data="recharge_amount_500")],
            [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list"),
             InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ]
        self.user_states[uid] = {'state': 'waiting_recharge_amount'}
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def _show_created_recharge_order(self, chat_or_query, order: Dict, edit_query=None):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list"),
             InlineKeyboardButton("❌ 取消订单", callback_data=f"recharge_cancel_{str(order['_id'])}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ])
        try:
            chat_id = (edit_query.message.chat_id if edit_query
                       else (chat_or_query.chat_id if hasattr(chat_or_query, 'chat_id')
                             else chat_or_query.message.chat_id))
            self.core.send_plain_qr_with_caption(chat_id, order, kb)
        except Exception as e:
            logger.warning(f"发送二维码caption失败: {e}")
            fallback = self._format_recharge_text(order)
            if edit_query:
                self.safe_edit_message(edit_query, fallback, kb.inline_keyboard, parse_mode=ParseMode.HTML)
            else:
                chat_or_query.reply_text(fallback, reply_markup=kb, parse_mode=ParseMode.HTML)

    def handle_recharge_amount_input(self, update: Update, amount: Decimal):
        uid = update.effective_user.id
        ok, msg, order = self.core.create_recharge_order(uid, amount)
        if not ok:
            update.message.reply_text(f"❌ {msg}")
            return
        self.user_states.pop(uid, None)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list"),
             InlineKeyboardButton("❌ 取消订单", callback_data=f"recharge_cancel_{str(order['_id'])}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ])
        try:
            self.core.send_plain_qr_with_caption(update.message.chat_id, order, kb)
        except Exception as e:
            logger.warning(f"发送二维码caption失败(text输入): {e}")
            update.message.reply_text(self._format_recharge_text(order), reply_markup=kb, parse_mode=ParseMode.HTML)

    def show_recharge_list(self, query):
        uid = query.from_user.id
        recs = self.core.list_recharges(uid, limit=10, include_canceled=False)
        if not recs:
            self.safe_edit_message(query, "📜 最近充值记录\n\n暂无记录", [[InlineKeyboardButton("🔙 返回", callback_data="recharge")]], parse_mode=None)
            return
        text = "📜 最近充值记录（最新优先）\n\n"
        for r in recs:
            st = r.get('status')
            ba = Decimal(str(r.get('base_amount', 0))).quantize(Decimal("0.01"))
            ea = Decimal(str(r.get('expected_amount', 0))).quantize(Decimal("0.0001"))
            ct = r.get('created_time'); ct_s = self.core._to_beijing(ct).strftime('%m-%d %H:%M') if ct else '-'
            ex = r.get('expire_time'); ex_s = self.core._to_beijing(ex).strftime('%m-%d %H:%M') if ex else '-'
            tx = r.get('tx_id') or '-'
            text += f"• {st} | 基:{ba}U | 应:{ea}U | 创建:{ct_s} | 过期:{ex_s} | Tx:{self.H(tx[:14] + '...' if len(tx)>14 else tx)}\n"
        kb = [
            [InlineKeyboardButton("🔙 返回充值", callback_data="recharge"),
             InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    # ========== 价格管理 / 报表 ==========
    def show_price_management(self, query, page: int = 1):
        uid = query.from_user.id
        if not self.core.config.is_admin(uid):
            self.safe_edit_message(query, "❌ 无权限", [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]], parse_mode=None)
            return
        res = self.core.get_agent_product_list(uid, page)
        prods = res['products']
        if not prods:
            self.safe_edit_message(query, "❌ 暂无商品可管理", [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]], parse_mode=None)
            return
        text = f"💰 价格管理（第{page}页）\n\n"
        kb = []
        for p in prods:
            info = p['product_info'][0] if p['product_info'] else {}
            name = info.get('projectname', 'N/A')
            nowuid = p.get('original_nowuid', '')
            
            # ✅ 实时获取总部价格
            origin_price = float(info.get('money', 0))
            
            # ✅ 获取代理的加价标记
            agent_markup = float(p.get('agent_markup', 0))
            
            # ✅ 实时计算代理价格
            agent_price = round(origin_price + agent_markup, 2)
            
            # ✅ 计算当前利润率
            profit_rate = (agent_markup / origin_price * 100) if origin_price else 0
            
            stock = self.core.get_product_stock(nowuid)
            text += f"{self.H(name)}\n总部:{origin_price}U  加价:{agent_markup:.2f}U  代理价:{agent_price}U  利润率:{profit_rate:.1f}%  库:{stock}\n\n"
            kb.append([InlineKeyboardButton(f"📝 {name[:18]}", callback_data=f"edit_price_{nowuid}")])
        pag = []
        if page > 1:
            pag.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"price_page_{page-1}"))
        if res['current_page'] < res['total_pages']:
            pag.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"price_page_{page+1}"))
        if pag:
            kb.append(pag)
        kb.append([InlineKeyboardButton("🏠 主菜单", callback_data="back_main")])
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_price_edit(self, query, nowuid: str):
        prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
        if not prod:
            self.safe_edit_message(query, "❌ 商品不存在", [[InlineKeyboardButton("🔙 返回", callback_data="price_management")]], parse_mode=None)
            return
        ap_info = self.core.config.agent_product_prices.find_one({
            'agent_bot_id': self.core.config.AGENT_BOT_ID, 'original_nowuid': nowuid
        })
        if not ap_info:
            self.safe_edit_message(query, "❌ 代理价格配置不存在", [[InlineKeyboardButton("🔙 返回", callback_data="price_management")]], parse_mode=None)
            return
        
        # ✅ 实时获取总部价格
        op = float(prod.get('money', 0))
        
        # ✅ 获取代理加价标记
        agent_markup = float(ap_info.get('agent_markup', 0))
        
        # ✅ 实时计算代理价格
        agent_price = round(op + agent_markup, 2)
        
        # ✅ 计算利润率
        profit_rate = (agent_markup / op * 100) if op > 0 else 0
        
        stock = self.core.get_product_stock(nowuid)
        text = f"""📝 编辑商品价格

🏷️ 商品: {self.H(prod['projectname'])}
📦 库存: {stock}
💼 编号: {self.H(nowuid)}

💰 当前价格:
• 总部: {op}U
• 加价: {agent_markup:.2f}U
• 代理价: {agent_price:.2f}U
• 利润率: {profit_rate:.1f}%

请直接发送新的代理价格数字，例如: {op + 0.2:.2f}
"""
        self.user_states[query.from_user.id] = {'state': 'waiting_price', 'product_nowuid': nowuid, 'original_price': op}
        kb = [
            [InlineKeyboardButton("🔄 切换状态", callback_data=f"toggle_status_{nowuid}"),
             InlineKeyboardButton("📊 利润预算", callback_data=f"profit_calc_{nowuid}")],
            [InlineKeyboardButton("🔙 返回管理", callback_data="price_management")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=ParseMode.HTML)

    def show_profit_calculator(self, query, nowuid: str):
        ap_info = self.core.config.agent_product_prices.find_one({
            'agent_bot_id': self.core.config.AGENT_BOT_ID, 'original_nowuid': nowuid
        })
        if not ap_info:
            self.safe_edit_message(query, "❌ 商品不存在", [[InlineKeyboardButton("🔙 返回", callback_data="price_management")]], parse_mode=None)
            return
        
        # ✅ 实时获取总部价格
        prod = self.core.config.ejfl.find_one({'nowuid': nowuid})
        op = float(prod.get('money', 0)) if prod else 0
        
        name = ap_info.get('product_name', 'N/A')
        text = f"📊 利润计算器 - {self.H(name)}\n总部: {op}U（实时价格）\n\n"
        kb = []
        
        for rate in [10, 20, 30, 50, 80, 100]:
            # ✅ 计算新的加价标记
            new_markup = round(op * rate / 100, 2)
            # ✅ 实时计算代理价格
            new_agent_price = round(op + new_markup, 2)
            text += f"{rate}% → {new_agent_price:.2f}U (加价:{new_markup:.2f})\n"
            kb.append([InlineKeyboardButton(f"设置 {rate}%({new_agent_price})", callback_data=f"set_price_{nowuid}_{new_agent_price}")])
        
        kb.append([InlineKeyboardButton("🔙 返回编辑", callback_data=f"edit_price_{nowuid}")])
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_system_reports(self, query):
        uid = query.from_user.id
        if not self.core.config.is_admin(uid):
            self.safe_edit_message(query, "❌ 无权限", [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]], parse_mode=None)
            return
        text = ("📊 系统报表中心\n\n"
                "请选择需要查看的报表类型：")
        kb = [
            [InlineKeyboardButton("📈 销售报表(30天)", callback_data="report_sales_30"),
             InlineKeyboardButton("👥 用户报表", callback_data="report_users")],
            [InlineKeyboardButton("📦 商品报表", callback_data="report_products"),
             InlineKeyboardButton("💰 财务报表(30天)", callback_data="report_financial_30")],
            [InlineKeyboardButton("📊 综合概览", callback_data="report_overview_quick"),
             InlineKeyboardButton("🔄 刷新数据", callback_data="system_reports")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_sales_report(self, query, days: int = 30):
        s = self.core.get_sales_statistics(days)
        text = (f"📈 销售报表（{days}天）\n"
                f"总订单:{s['total_orders']}  总销售额:{s['total_revenue']:.2f}U  总销量:{s['total_quantity']}\n"
                f"平均订单额:{s['avg_order_value']:.2f}U\n\n"
                f"今日 订单:{s['today_orders']}  销售:{s['today_revenue']:.2f}U  量:{s['today_quantity']}\n\n"
                "🏆 热销TOP5：\n")
        if s['popular_products']:
            for i,p in enumerate(s['popular_products'],1):
                text += f"{i}. {self.H(p['_id'])}  数量:{p['total_sold']}  销售:{p['total_revenue']:.2f}U\n"
        else:
            text += "暂无数据\n"
        kb = [
            [InlineKeyboardButton("📅 7天", callback_data="report_sales_7"),
             InlineKeyboardButton("📅 30天", callback_data="report_sales_30"),
             InlineKeyboardButton("📅 90天", callback_data="report_sales_90")],
            [InlineKeyboardButton("🔄 刷新", callback_data=f"report_sales_{days}"),
             InlineKeyboardButton("🔙 返回报表", callback_data="system_reports")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_user_report(self, query):
        st = self.core.get_user_statistics()
        text = (f"👥 用户统计报表\n"
                f"总:{st['total_users']}  活跃:{st['active_users']}  今日新增:{st['today_new_users']}  活跃率:{st['activity_rate']}%\n"
                f"余额总:{st['total_balance']:.2f}U  平均:{st['avg_balance']:.2f}U  消费总:{st['total_spent']:.2f}U\n"
                f"等级分布  铜:{st['spending_levels']['bronze']}  银:{st['spending_levels']['silver']}  金:{st['spending_levels']['gold']}")
        kb=[[InlineKeyboardButton("🔄 刷新", callback_data="report_users"),
             InlineKeyboardButton("🔙 返回报表", callback_data="system_reports")]]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_overview_report(self, query):
        s = self.core.get_sales_statistics(30)
        u = self.core.get_user_statistics()
        text = (f"📊 系统概览报表(30天)\n\n"
                f"用户:{u['total_users']}  活跃:{u['active_users']}  今日新增:{u['today_new_users']}\n"
                f"订单:{s['total_orders']}  销售:{s['total_revenue']:.2f}U  今日:{s['today_revenue']:.2f}U\n"
                f"平均订单额:{s['avg_order_value']:.2f}U  活跃率:{u['activity_rate']}%")
        kb=[[InlineKeyboardButton("🔄 刷新", callback_data="report_overview_quick"),
             InlineKeyboardButton("🔙 返回报表", callback_data="system_reports")]]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_product_report(self, query):
        p = self.core.get_product_statistics()
        text = (f"📦 商品统计报表\n"
                f"商品:{p['total_products']}  启用:{p['active_products']}  禁用:{p['inactive_products']}\n"
                f"库存:{p['total_stock']}  已售:{p['sold_stock']}  周转率:{p['stock_turnover_rate']}%\n"
                f"平均利润率:{p['avg_profit_rate']}%  最高:{p['highest_profit_rate']}%  最低:{p['lowest_profit_rate']}%")
        kb=[[InlineKeyboardButton("🔄 刷新", callback_data="report_products"),
             InlineKeyboardButton("🔙 返回报表", callback_data="system_reports")]]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_financial_report(self, query, days: int = 30):
        f = self.core.get_financial_statistics(days)
        text = (f"💰 财务报表（{days}天）\n"
                f"总收入:{f['total_revenue']:.2f}U  订单数:{f['order_count']}  平均订单:{f['avg_order_value']:.2f}U\n"
                f"预估利润:{f['estimated_profit']:.2f}U  利润率:{f['profit_margin']}%")
        kb = [
            [InlineKeyboardButton("📅 7天", callback_data="report_financial_7"),
             InlineKeyboardButton("📅 30天", callback_data="report_financial_30"),
             InlineKeyboardButton("📅 90天", callback_data="report_financial_90")],
            [InlineKeyboardButton("🔄 刷新", callback_data=f"report_financial_{days}"),
             InlineKeyboardButton("🔙 返回报表", callback_data="system_reports")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    # ========== 国家/地区商品查询 ==========
    
    # 国家代码映射表（国际区号 -> (国家名, 旗帜emoji)）
    COUNTRY_CODE_MAP = {
        '+1': ('美国/加拿大', '🇺🇸'),
        '+7': ('俄罗斯/哈萨克斯坦', '🇷🇺'),
        '+20': ('埃及', '🇪🇬'),
        '+27': ('南非', '🇿🇦'),
        '+30': ('希腊', '🇬🇷'),
        '+31': ('荷兰', '🇳🇱'),
        '+32': ('比利时', '🇧🇪'),
        '+33': ('法国', '🇫🇷'),
        '+34': ('西班牙', '🇪🇸'),
        '+36': ('匈牙利', '🇭🇺'),
        '+39': ('意大利', '🇮🇹'),
        '+40': ('罗马尼亚', '🇷🇴'),
        '+41': ('瑞士', '🇨🇭'),
        '+43': ('奥地利', '🇦🇹'),
        '+44': ('英国', '🇬🇧'),
        '+45': ('丹麦', '🇩🇰'),
        '+46': ('瑞典', '🇸🇪'),
        '+47': ('挪威', '🇳🇴'),
        '+48': ('波兰', '🇵🇱'),
        '+49': ('德国', '🇩🇪'),
        '+51': ('秘鲁', '🇵🇪'),
        '+52': ('墨西哥', '🇲🇽'),
        '+53': ('古巴', '🇨🇺'),
        '+54': ('阿根廷', '🇦🇷'),
        '+55': ('巴西', '🇧🇷'),
        '+56': ('智利', '🇨🇱'),
        '+57': ('哥伦比亚', '🇨🇴'),
        '+58': ('委内瑞拉', '🇻🇪'),
        '+60': ('马来西亚', '🇲🇾'),
        '+61': ('澳大利亚', '🇦🇺'),
        '+62': ('印度尼西亚', '🇮🇩'),
        '+63': ('菲律宾', '🇵🇭'),
        '+64': ('新西兰', '🇳🇿'),
        '+65': ('新加坡', '🇸🇬'),
        '+66': ('泰国', '🇹🇭'),
        '+81': ('日本', '🇯🇵'),
        '+82': ('韩国', '🇰🇷'),
        '+84': ('越南', '🇻🇳'),
        '+86': ('中国', '🇨🇳'),
        '+90': ('土耳其', '🇹🇷'),
        '+91': ('印度', '🇮🇳'),
        '+92': ('巴基斯坦', '🇵🇰'),
        '+93': ('阿富汗', '🇦🇫'),
        '+94': ('斯里兰卡', '🇱🇰'),
        '+95': ('缅甸', '🇲🇲'),
        '+98': ('伊朗', '🇮🇷'),
        '+212': ('摩洛哥', '🇲🇦'),
        '+213': ('阿尔及利亚', '🇩🇿'),
        '+216': ('突尼斯', '🇹🇳'),
        '+218': ('利比亚', '🇱🇾'),
        '+220': ('冈比亚', '🇬🇲'),
        '+221': ('塞内加尔', '🇸🇳'),
        '+223': ('马里', '🇲🇱'),
        '+224': ('几内亚', '🇬🇳'),
        '+225': ('科特迪瓦', '🇨🇮'),
        '+226': ('布基纳法索', '🇧🇫'),
        '+227': ('尼日尔', '🇳🇪'),
        '+228': ('多哥', '🇹🇬'),
        '+229': ('贝宁', '🇧🇯'),
        '+230': ('毛里求斯', '🇲🇺'),
        '+231': ('利比里亚', '🇱🇷'),
        '+232': ('塞拉利昂', '🇸🇱'),
        '+233': ('加纳', '🇬🇭'),
        '+234': ('尼日利亚', '🇳🇬'),
        '+235': ('乍得', '🇹🇩'),
        '+236': ('中非', '🇨🇫'),
        '+237': ('喀麦隆', '🇨🇲'),
        '+238': ('佛得角', '🇨🇻'),
        '+239': ('圣多美和普林西比', '🇸🇹'),
        '+240': ('赤道几内亚', '🇬🇶'),
        '+241': ('加蓬', '🇬🇦'),
        '+242': ('刚果', '🇨🇬'),
        '+243': ('刚果民主共和国', '🇨🇩'),
        '+244': ('安哥拉', '🇦🇴'),
        '+245': ('几内亚比绍', '🇬🇼'),
        '+246': ('英属印度洋领地', '🇮🇴'),
        '+248': ('塞舌尔', '🇸🇨'),
        '+249': ('苏丹', '🇸🇩'),
        '+250': ('卢旺达', '🇷🇼'),
        '+251': ('埃塞俄比亚', '🇪🇹'),
        '+252': ('索马里', '🇸🇴'),
        '+253': ('吉布提', '🇩🇯'),
        '+254': ('肯尼亚', '🇰🇪'),
        '+255': ('坦桑尼亚', '🇹🇿'),
        '+256': ('乌干达', '🇺🇬'),
        '+257': ('布隆迪', '🇧🇮'),
        '+258': ('莫桑比克', '🇲🇿'),
        '+260': ('赞比亚', '🇿🇲'),
        '+261': ('马达加斯加', '🇲🇬'),
        '+262': ('留尼汪', '🇷🇪'),
        '+263': ('津巴布韦', '🇿🇼'),
        '+264': ('纳米比亚', '🇳🇦'),
        '+265': ('马拉维', '🇲🇼'),
        '+266': ('莱索托', '🇱🇸'),
        '+267': ('博茨瓦纳', '🇧🇼'),
        '+268': ('斯威士兰', '🇸🇿'),
        '+269': ('科摩罗', '🇰🇲'),
        '+290': ('圣赫勒拿', '🇸🇭'),
        '+291': ('厄立特里亚', '🇪🇷'),
        '+297': ('阿鲁巴', '🇦🇼'),
        '+298': ('法罗群岛', '🇫🇴'),
        '+299': ('格陵兰', '🇬🇱'),
        '+350': ('直布罗陀', '🇬🇮'),
        '+351': ('葡萄牙', '🇵🇹'),
        '+352': ('卢森堡', '🇱🇺'),
        '+353': ('爱尔兰', '🇮🇪'),
        '+354': ('冰岛', '🇮🇸'),
        '+355': ('阿尔巴尼亚', '🇦🇱'),
        '+356': ('马耳他', '🇲🇹'),
        '+357': ('塞浦路斯', '🇨🇾'),
        '+358': ('芬兰', '🇫🇮'),
        '+359': ('保加利亚', '🇧🇬'),
        '+370': ('立陶宛', '🇱🇹'),
        '+371': ('拉脱维亚', '🇱🇻'),
        '+372': ('爱沙尼亚', '🇪🇪'),
        '+373': ('摩尔多瓦', '🇲🇩'),
        '+374': ('亚美尼亚', '🇦🇲'),
        '+375': ('白俄罗斯', '🇧🇾'),
        '+376': ('安道尔', '🇦🇩'),
        '+377': ('摩纳哥', '🇲🇨'),
        '+378': ('圣马力诺', '🇸🇲'),
        '+380': ('乌克兰', '🇺🇦'),
        '+381': ('塞尔维亚', '🇷🇸'),
        '+382': ('黑山', '🇲🇪'),
        '+383': ('科索沃', '🇽🇰'),
        '+385': ('克罗地亚', '🇭🇷'),
        '+386': ('斯洛文尼亚', '🇸🇮'),
        '+387': ('波黑', '🇧🇦'),
        '+389': ('北马其顿', '🇲🇰'),
        '+420': ('捷克', '🇨🇿'),
        '+421': ('斯洛伐克', '🇸🇰'),
        '+423': ('列支敦士登', '🇱🇮'),
        '+500': ('福克兰群岛', '🇫🇰'),
        '+501': ('伯利兹', '🇧🇿'),
        '+502': ('危地马拉', '🇬🇹'),
        '+503': ('萨尔瓦多', '🇸🇻'),
        '+504': ('洪都拉斯', '🇭🇳'),
        '+505': ('尼加拉瓜', '🇳🇮'),
        '+506': ('哥斯达黎加', '🇨🇷'),
        '+507': ('巴拿马', '🇵🇦'),
        '+508': ('圣皮埃尔和密克隆', '🇵🇲'),
        '+509': ('海地', '🇭🇹'),
        '+590': ('瓜德罗普', '🇬🇵'),
        '+591': ('玻利维亚', '🇧🇴'),
        '+592': ('圭亚那', '🇬🇾'),
        '+593': ('厄瓜多尔', '🇪🇨'),
        '+594': ('法属圭亚那', '🇬🇫'),
        '+595': ('巴拉圭', '🇵🇾'),
        '+596': ('马提尼克', '🇲🇶'),
        '+597': ('苏里南', '🇸🇷'),
        '+598': ('乌拉圭', '🇺🇾'),
        '+599': ('荷属安的列斯', '🇨🇼'),
        '+670': ('东帝汶', '🇹🇱'),
        '+672': ('南极洲', '🇦🇶'),
        '+673': ('文莱', '🇧🇳'),
        '+674': ('瑙鲁', '🇳🇷'),
        '+675': ('巴布亚新几内亚', '🇵🇬'),
        '+676': ('汤加', '🇹🇴'),
        '+677': ('所罗门群岛', '🇸🇧'),
        '+678': ('瓦努阿图', '🇻🇺'),
        '+679': ('斐济', '🇫🇯'),
        '+680': ('帕劳', '🇵🇼'),
        '+681': ('瓦利斯和富图纳', '🇼🇫'),
        '+682': ('库克群岛', '🇨🇰'),
        '+683': ('纽埃', '🇳🇺'),
        '+685': ('萨摩亚', '🇼🇸'),
        '+686': ('基里巴斯', '🇰🇮'),
        '+687': ('新喀里多尼亚', '🇳🇨'),
        '+688': ('图瓦卢', '🇹🇻'),
        '+689': ('法属波利尼西亚', '🇵🇫'),
        '+690': ('托克劳', '🇹🇰'),
        '+691': ('密克罗尼西亚', '🇫🇲'),
        '+692': ('马绍尔群岛', '🇲🇭'),
        '+850': ('朝鲜', '🇰🇵'),
        '+852': ('香港', '🇭🇰'),
        '+853': ('澳门', '🇲🇴'),
        '+855': ('柬埔寨', '🇰🇭'),
        '+856': ('老挝', '🇱🇦'),
        '+880': ('孟加拉国', '🇧🇩'),
        '+886': ('台湾', '🇹🇼'),
        '+960': ('马尔代夫', '🇲🇻'),
        '+961': ('黎巴嫩', '🇱🇧'),
        '+962': ('约旦', '🇯🇴'),
        '+963': ('叙利亚', '🇸🇾'),
        '+964': ('伊拉克', '🇮🇶'),
        '+965': ('科威特', '🇰🇼'),
        '+966': ('沙特阿拉伯', '🇸🇦'),
        '+967': ('也门', '🇾🇪'),
        '+968': ('阿曼', '🇴🇲'),
        '+970': ('巴勒斯坦', '🇵🇸'),
        '+971': ('阿联酋', '🇦🇪'),
        '+972': ('以色列', '🇮🇱'),
        '+973': ('巴林', '🇧🇭'),
        '+974': ('卡塔尔', '🇶🇦'),
        '+975': ('不丹', '🇧🇹'),
        '+976': ('蒙古', '🇲🇳'),
        '+977': ('尼泊尔', '🇳🇵'),
        '+992': ('塔吉克斯坦', '🇹🇯'),
        '+993': ('土库曼斯坦', '🇹🇲'),
        '+994': ('阿塞拜疆', '🇦🇿'),
        '+995': ('格鲁吉亚', '🇬🇪'),
        '+996': ('吉尔吉斯斯坦', '🇰🇬'),
        '+998': ('乌兹别克斯坦', '🇺🇿'),
    }
    
    def _is_country_code_query(self, text: str) -> bool:
        """检测消息是否为国家代码查询（包含+号）"""
        return '+' in text
    
    def _extract_country_codes(self, text: str) -> List[str]:
        """从消息中提取所有国家代码"""
        import re
        # 匹配 +数字 模式（1-4位数字）
        pattern = r'\+\d{1,4}'
        codes = re.findall(pattern, text)
        # 去重并保持顺序
        seen = set()
        unique_codes = []
        for code in codes:
            if code not in seen:
                seen.add(code)
                unique_codes.append(code)
        return unique_codes
    
    def _search_products_by_country_codes(self, country_codes: List[str]) -> List[Dict]:
        """根据国家代码搜索商品"""
        try:
            # 构建搜索条件：商品名称包含任一国家代码或对应国家名
            search_patterns = []
            country_names = []
            
            for code in country_codes:
                # 添加代码本身作为搜索词
                search_patterns.append(code)
                # 添加对应的国家名
                if code in self.COUNTRY_CODE_MAP:
                    country_name, _ = self.COUNTRY_CODE_MAP[code]
                    # 如果国家名包含"/"，拆分为多个名称
                    if '/' in country_name:
                        for name in country_name.split('/'):
                            country_names.append(name.strip())
                    else:
                        country_names.append(country_name)
            
            # 合并所有搜索模式
            all_patterns = search_patterns + country_names
            
            # 构建MongoDB查询
            # 1. 先查询代理端已激活的商品
            agent_products = list(self.core.config.agent_product_prices.find({
                'agent_bot_id': self.core.config.AGENT_BOT_ID,
                'is_active': True
            }, {'original_nowuid': 1}))
            
            if not agent_products:
                return []
            
            active_nowuids = [p['original_nowuid'] for p in agent_products]
            
            # 2. 在总部商品表中搜索匹配的商品
            # ✅ 转义正则表达式特殊字符（特别是"+"号），避免MongoDB regex错误
            query = {
                'nowuid': {'$in': active_nowuids},
                '$or': [
                    {'projectname': {'$regex': re.escape(pattern), '$options': 'i'}}
                    for pattern in all_patterns
                ]
            }
            
            products = list(self.core.config.ejfl.find(query))
            
            # 3. 为每个商品添加价格和库存信息
            result = []
            for p in products:
                nowuid = p.get('nowuid')
                if not nowuid:
                    continue
                
                # 获取代理价格
                price = self.core.get_product_price(nowuid)
                if price is None:
                    continue
                
                # 获取库存
                stock = self.core.get_product_stock(nowuid)
                
                result.append({
                    'nowuid': nowuid,
                    'projectname': p.get('projectname', ''),
                    'price': price,
                    'stock': stock,
                    'leixing': p.get('leixing', '')
                })
            
            # 按库存降序排序
            result.sort(key=lambda x: x['stock'], reverse=True)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 搜索国家代码商品失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def handle_country_code_search(self, update: Update, context: CallbackContext, message_text: str):
        """处理国家代码商品搜索"""
        try:
            # 提取国家代码
            country_codes = self._extract_country_codes(message_text)
            
            if not country_codes:
                # 没有找到有效的国家代码，提示用户
                update.message.reply_text(
                    "⚠️ 请带+号才可以搜索\n\n"
                    "示例：\n"
                    "• +54 (搜索阿根廷商品)\n"
                    "• +34 +86 (搜索西班牙和中国商品)\n"
                    "• +1 (搜索美国/加拿大商品)",
                    parse_mode=None
                )
                return
            
            # 搜索商品
            products = self._search_products_by_country_codes(country_codes)
            
            if not products:
                # 构建国家名称列表
                country_names = []
                for code in country_codes:
                    if code in self.COUNTRY_CODE_MAP:
                        name, flag = self.COUNTRY_CODE_MAP[code]
                        country_names.append(f"{flag} {name} ({code})")
                    else:
                        country_names.append(code)
                
                countries_text = "、".join(country_names)
                update.message.reply_text(
                    f"😔 未找到相关商品\n\n"
                    f"搜索范围：{countries_text}\n\n"
                    f"可能原因：\n"
                    f"• 该地区商品暂时缺货\n"
                    f"• 商品名称中未包含国家代码或国家名\n\n"
                    f"💡 建议：\n"
                    f"• 尝试其他国家代码\n"
                    f"• 通过商品分类浏览全部商品",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🛍️ 商品中心", callback_data="products"),
                        InlineKeyboardButton("🏠 主菜单", callback_data="back_main")
                    ]])
                )
                return
            
            # 显示第一页结果
            self._show_country_products_page(update.message, country_codes, products, page=1)
            
        except Exception as e:
            logger.error(f"❌ 处理国家代码搜索失败: {e}")
            import traceback
            traceback.print_exc()
            update.message.reply_text(
                "❌ 搜索失败，请稍后重试",
                parse_mode=None
            )
    
    def _show_country_products_page(self, message, country_codes: List[str], all_products: List[Dict], page: int = 1, per_page: int = 10, is_edit: bool = False):
        """显示国家商品搜索结果（分页）
        
        Args:
            message: Message对象（用户消息或bot消息）
            country_codes: 国家代码列表
            all_products: 所有商品列表
            page: 当前页码
            per_page: 每页显示数量
            is_edit: 是否为编辑模式（True=编辑现有消息，False=发送新消息）
        """
        try:
            # 构建标题
            country_names = []
            for code in country_codes:
                if code in self.COUNTRY_CODE_MAP:
                    name, flag = self.COUNTRY_CODE_MAP[code]
                    country_names.append(f"{flag} {name}")
                else:
                    country_names.append(code)
            
            title = "、".join(country_names)
            codes_display = " ".join(country_codes)
            
            # 计算分页
            total = len(all_products)
            total_pages = (total + per_page - 1) // per_page
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_products = all_products[start_idx:end_idx]
            
            # 计算总库存
            total_stock = sum(p['stock'] for p in all_products)
            
            # 构建消息文本
            text = f"🌍 {title}商品列表 ({codes_display})\n\n"
            text += f"📊 搜索结果\n"
            text += f"  • 总商品数：{total}\n"
            text += f"  • 总库存：{total_stock}\n"
            text += f"  • 当前页：{page}/{total_pages}\n\n"
            
            # 构建按钮
            kb = []
            for p in page_products:
                name = p['projectname']
                price = p['price']
                stock = p['stock']
                nowuid = p['nowuid']
                
                # 截断商品名避免按钮太长
                if len(name) > 25:
                    name = name[:25] + "..."
                
                button_text = f"{name} | {price}U | [{stock}个]"
                kb.append([InlineKeyboardButton(button_text, callback_data=f"product_{nowuid}")])
            
            # 分页按钮
            if total_pages > 1:
                pag = []
                if page > 1:
                    pag.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"country_page_{page-1}"))
                pag.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="no_action"))
                if page < total_pages:
                    pag.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"country_page_{page+1}"))
                kb.append(pag)
            
            # 底部按钮
            kb.append([
                InlineKeyboardButton("🛍️ 商品中心", callback_data="products"),
                InlineKeyboardButton("🏠 主菜单", callback_data="back_main")
            ])
            
            # 发送或编辑消息
            if is_edit:
                # 编辑模式：更新现有bot消息（用于分页）
                message.edit_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=None
                )
            else:
                # 回复模式：发送新消息（用于首次搜索）
                message.reply_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=None
                )
            
            # 存储搜索状态用于分页
            # 将搜索结果缓存到用户状态中
            uid = message.chat.id if hasattr(message, 'chat') else message.from_user.id
            if not hasattr(self, 'country_search_cache'):
                self.country_search_cache = {}
            self.country_search_cache[uid] = {
                'country_codes': country_codes,
                'products': all_products
            }
            
        except Exception as e:
            logger.error(f"❌ 显示国家商品页面失败: {e}")
            import traceback
            traceback.print_exc()

    # ========== 其它 ==========
    def show_support_info(self, query):
        # Build display text using config
        display = self.core.config.SUPPORT_CONTACT_DISPLAY or f"@{self.core.config.SUPPORT_CONTACT_USERNAME}"
        text = f"📞 客服 {display}\n请描述问题 + 用户ID/订单号，便于快速处理。"
        kb = [
            [InlineKeyboardButton("💬 联系客服", url=self.core.config.SUPPORT_CONTACT_URL)],
            [InlineKeyboardButton("👤 个人中心", callback_data="profile"),
             InlineKeyboardButton("❓ 使用帮助", callback_data="help")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_help_info(self, query):
        # Build display text using config
        display = self.core.config.SUPPORT_CONTACT_DISPLAY or f"@{self.core.config.SUPPORT_CONTACT_USERNAME}"
        text = (
            "❓ 使用帮助\n\n"
            "• 购买：分类 -> 商品 -> 立即购买 -> 输入数量\n"
            "• 充值：进入充值 -> 选择金额或输入金额 -> 按识别金额精确转账\n"
            "• 自动监听入账，无需手动校验\n"
            f"• 有问题联系人工客服 {display}"
        )
        kb = [
            [InlineKeyboardButton("📞 联系客服", callback_data="support"),
             InlineKeyboardButton("🛍️ 商品中心", callback_data="products")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def show_language_menu(self, query):
        """显示语言选择菜单"""
        uid = query.from_user.id
        text = self.core.t(uid, 'lang.menu_title')
        kb = [
            [InlineKeyboardButton(self.core.t(uid, 'lang.zh_label'), callback_data="set_lang_zh")],
            [InlineKeyboardButton(self.core.t(uid, 'lang.en_label'), callback_data="set_lang_en")],
            [InlineKeyboardButton(self.core.t(uid, 'btn.back_main'), callback_data="back_main")]
        ]
        self.safe_edit_message(query, text, kb, parse_mode=None)

    def set_user_language(self, query, lang: str):
        """设置用户语言并返回主菜单"""
        uid = query.from_user.id
        success = self.core.set_user_language(uid, lang)
        if success:
            query.answer(self.core.t(uid, 'lang.set_ok'), show_alert=False)
            # 刷新主菜单以显示新语言
            self.show_main_menu(query)
        else:
            query.answer("❌ Failed to set language", show_alert=True)

    def show_order_history(self, query, page: int = 1):
        """显示用户订单历史（分页）- HQ风格紧凑列表"""
        uid = query.from_user.id
        
        try:
            # 使用新的 API 获取订单
            result = self.core.list_user_orders(uid, page=page, limit=10)
            orders = result['orders']
            total = result['total']
            total_pages = result['total_pages']
            
            if total == 0:
                self.safe_edit_message(
                    query,
                    "📦 购买记录\n\n暂无购买记录",
                    [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]],
                    parse_mode=None
                )
                return
            
            # 构建紧凑的标题栏
            latest_time = orders[0].get('timer', '-') if orders else '-'
            # 格式化时间，只显示到分钟
            try:
                if latest_time != '-' and len(latest_time) >= 16:
                    latest_time_display = latest_time[:16]  # YYYY-MM-DD HH:MM
                else:
                    latest_time_display = latest_time
            except:
                latest_time_display = '-'
            
            text = "📦 购买记录\n\n"
            text += f"📊 记录概览\n"
            text += f"• 总订单数：{total}\n"
            text += f"• 当前页显示：{len(orders)}\n"
            text += f"• 最近更新：{latest_time_display}\n\n"
            text += "💡 操作说明\n"
            text += "点击下面按钮查看订单详情或重新下载商品\n\n"
            
            # 为每个订单构建一个紧凑的按钮
            kb = []
            for order in orders:
                product_name = order.get('projectname', '未知商品')
                quantity = order.get('count', 1)
                order_time = order.get('timer', '未知时间')
                order_id = order.get('bianhao', '')
                
                # 格式化时间为 YYYY-MM-DD HH:MM（去掉秒）
                try:
                    if len(order_time) >= 16:
                        time_display = order_time[:16]  # 取前16个字符 YYYY-MM-DD HH:MM
                    else:
                        time_display = order_time
                except:
                    time_display = order_time
                
                # 截断商品名称以适应按钮宽度
                name_display = product_name[:20] if len(product_name) > 20 else product_name
                
                # 构建按钮文本："商品名 | 数量:N | YYYY-MM-DD HH:MM"
                button_text = f"{name_display} | 数量:{quantity} | {time_display}"
                
                # 添加订单详情按钮
                kb.append([InlineKeyboardButton(
                    button_text,
                    callback_data=f"order_detail_{order_id}"
                )])
            
            # 分页按钮
            pag = []
            if page > 1:
                pag.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"orders_page_{page-1}"))
            if page < total_pages:
                pag.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"orders_page_{page+1}"))
            if pag:
                kb.append(pag)
            
            # 返回主菜单按钮
            kb.append([InlineKeyboardButton("🏠 主菜单", callback_data="back_main")])
            
            self.safe_edit_message(query, text, kb, parse_mode=None)
            
        except Exception as e:
            logger.error(f"显示订单历史失败: {e}")
            import traceback
            traceback.print_exc()
            self.safe_edit_message(
                query,
                "❌ 加载订单历史失败",
                [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]],
                parse_mode=None
            )
    
    def show_order_detail(self, query, order_id: str):
        """显示订单详情"""
        uid = query.from_user.id
        
        try:
            # 查询订单
            order_coll = self.core.config.get_agent_gmjlu_collection()
            order = order_coll.find_one({
                'bianhao': order_id,
                'user_id': uid,
                'leixing': 'purchase'
            })
            
            if not order:
                query.answer("❌ 订单不存在或无权访问", show_alert=True)
                return
            
            # 提取订单信息
            product_name = order.get('projectname', '未知商品')
            quantity = order.get('count', 1)
            total_amount = float(order.get('ts', 0))
            unit_price = total_amount / max(quantity, 1)
            order_time = order.get('timer', '未知时间')
            category = order.get('category', '-')
            nowuid = order.get('nowuid', '')
            
            # 构建详情文本
            text = "📋 订单详情\n\n"
            text += f"📦 商品：{product_name}\n"
            text += f"🔢 数量：{quantity}\n"
            text += f"💴 单价：{unit_price:.2f}U\n"
            text += f"💰 总额：{total_amount:.2f}U\n"
            text += f"🕒 时间：{order_time}\n"
            if category and category != '-':
                text += f"📂 分类：{category}\n"
            text += f"📋 订单号：{order_id}\n"
            
            # 构建按钮
            kb = []
            
            # 第一行：再次购买 + 下载文件
            row1 = []
            if nowuid:
                row1.append(InlineKeyboardButton(
                    "🛒 再次购买",
                    callback_data=f"product_{nowuid}"
                ))
            row1.append(InlineKeyboardButton(
                "📥 下载文件",
                callback_data=f"redownload_{order_id}"
            ))
            if row1:
                kb.append(row1)
            
            # 第二行：返回列表
            kb.append([InlineKeyboardButton("🔙 返回列表", callback_data="orders")])
            
            self.safe_edit_message(query, text, kb, parse_mode=None)
            query.answer()
            
        except Exception as e:
            logger.error(f"显示订单详情失败: {e}")
            import traceback
            traceback.print_exc()
            query.answer("❌ 加载订单详情失败", show_alert=True)

    def handle_redownload_order(self, query, order_id: str):
        """处理重新下载订单文件（使用存储的 item_ids）"""
        uid = query.from_user.id
        
        try:
            # 查询订单
            order_coll = self.core.config.get_agent_gmjlu_collection()
            order = order_coll.find_one({
                'bianhao': order_id,
                'user_id': uid,
                'leixing': 'purchase'
            })
            
            if not order:
                query.answer("❌ 订单不存在或无权访问", show_alert=True)
                return
            
            # 获取商品信息
            nowuid = order.get('nowuid')
            if not nowuid:
                # 如果旧订单没有nowuid，尝试通过projectname查找
                product = self.core.config.ejfl.find_one({'projectname': order.get('projectname')})
                if product:
                    nowuid = product.get('nowuid')
                else:
                    query.answer("❌ 无法找到商品信息", show_alert=True)
                    return
            
            product = self.core.config.ejfl.find_one({'nowuid': nowuid})
            if not product:
                query.answer("❌ 商品已不存在", show_alert=True)
                return
            
            product_name = product.get('projectname', '')
            quantity = order.get('count', 1)
            
            # ✅ 优先使用订单中存储的 item_ids（新订单）
            item_ids = order.get('item_ids')
            items = []
            
            if item_ids:
                # 新订单：使用存储的 item_ids
                logger.info(f"使用存储的 item_ids 重新下载订单 {order_id}，共 {len(item_ids)} 个商品")
                items = list(self.core.config.hb.find({'_id': {'$in': item_ids}}))
                
                if len(items) != len(item_ids):
                    logger.warning(f"部分商品项已丢失：期望 {len(item_ids)} 个，实际找到 {len(items)} 个")
            
            # ✅ 回退方案1：使用 first_item_id（调试/向后兼容）
            if not items:
                first_item_id = order.get('first_item_id')
                if first_item_id:
                    try:
                        first_item = self.core.config.hb.find_one({'_id': ObjectId(first_item_id)})
                        if first_item:
                            items.append(first_item)
                            logger.info(f"使用 first_item_id 找到第一个商品，尝试查找其它商品")
                    except:
                        pass
            
            # ✅ 回退方案2：查找该用户购买的同类商品（旧订单或数据丢失）
            if not items or len(items) < quantity:
                logger.warning(f"使用回退方案查找订单 {order_id} 的商品")
                fallback_items = list(self.core.config.hb.find({
                    'nowuid': nowuid,
                    'state': 1,
                    'gmid': uid
                }).limit(quantity))
                
                if fallback_items:
                    items = fallback_items
                    logger.info(f"回退方案找到 {len(items)} 个商品")
            
            # ✅ 最后的回退：创建临时项用于文件发送
            if not items:
                logger.warning(f"无法找到订单 {order_id} 的原始商品，创建临时项")
                query.answer("⚠️ 未找到原始商品文件，正在尝试重新获取...", show_alert=False)
                item_type = product.get('leixing', '')
                items = [{
                    'nowuid': nowuid,
                    'leixing': item_type,
                    'projectname': product_name
                }] * quantity
            
            # 重新发送文件
            files_sent = self.core.send_batch_files_to_user(uid, items, product_name, order_id)
            
            if files_sent > 0:
                query.answer("✅ 文件已重新发送，请查收！", show_alert=True)
            else:
                query.answer("❌ 文件发送失败，请联系客服", show_alert=True)
                
        except Exception as e:
            logger.error(f"重新下载订单文件失败: {e}")
            import traceback
            traceback.print_exc()
            query.answer("❌ 下载失败，请稍后重试", show_alert=True)

    # ========== 回调分发 ==========
    def button_callback(self, update: Update, context: CallbackContext):
        q = update.callback_query
        d = q.data
        try:
            logger.info(f"[DEBUG] callback data: {d}")

            # 基础导航
            if d == "products":
                self.show_product_categories(q); q.answer(); return
            elif d == "profile":
                self.show_user_profile(q); q.answer(); return
            elif d == "recharge":
                self.show_recharge_options(q); q.answer(); return
            elif d == "orders":
                self.show_order_history(q); q.answer(); return
            elif d.startswith("orders_page_"):
                self.show_order_history(q, int(d.replace("orders_page_",""))); q.answer(); return
            elif d.startswith("order_detail_"):
                self.show_order_detail(q, d.replace("order_detail_","")); return
            elif d.startswith("redownload_"):
                self.handle_redownload_order(q, d.replace("redownload_","")); return
            elif d == "support":
                self.show_support_info(q); q.answer(); return
            elif d == "help":
                self.show_help_info(q); q.answer(); return
            elif d == "back_main":
                self.show_main_menu(q); q.answer(); return
            elif d == "back_products":
                self.show_product_categories(q); q.answer(); return
            
            # 语言选择
            elif d == "language_menu":
                self.show_language_menu(q); q.answer(); return
            elif d == "set_lang_zh":
                self.set_user_language(q, "zh"); return
            elif d == "set_lang_en":
                self.set_user_language(q, "en"); return
            
            # 国家/地区商品查询分页
            elif d.startswith("country_page_"):
                try:
                    page = int(d.replace("country_page_", ""))
                    uid = q.from_user.id
                    if hasattr(self, 'country_search_cache') and uid in self.country_search_cache:
                        cache = self.country_search_cache[uid]
                        self._show_country_products_page(
                            q.message, 
                            cache['country_codes'], 
                            cache['products'], 
                            page=page,
                            is_edit=True  # ✅ 分页时编辑现有消息
                        )
                    else:
                        q.answer("搜索已过期，请重新搜索", show_alert=True)
                except Exception as e:
                    logger.error(f"处理国家商品分页失败: {e}")
                    q.answer("操作失败", show_alert=True)
                q.answer()
                return

            # 价格管理 / 报表
            elif d == "price_management":
                self.show_price_management(q); q.answer(); return
            elif d.startswith("price_page_"):
                self.show_price_management(q, int(d.replace("price_page_",""))); q.answer(); return
            elif d.startswith("edit_price_"):
                self.show_price_edit(q, d.replace("edit_price_","")); q.answer(); return
            elif d == "system_reports":
                self.show_system_reports(q); q.answer(); return
            elif d == "report_sales_7":
                self.show_sales_report(q,7); q.answer(); return
            elif d == "report_sales_30":
                self.show_sales_report(q,30); q.answer(); return
            elif d == "report_sales_90":
                self.show_sales_report(q,90); q.answer(); return
            elif d == "report_users":
                self.show_user_report(q); q.answer(); return
            elif d == "report_overview_quick":
                self.show_overview_report(q); q.answer(); return
            elif d == "report_products":
                self.show_product_report(q); q.answer(); return
            elif d == "report_financial_7":
                self.show_financial_report(q,7); q.answer(); return
            elif d == "report_financial_30":
                self.show_financial_report(q,30); q.answer(); return
            elif d == "report_financial_90":
                self.show_financial_report(q,90); q.answer(); return

            elif d.startswith("toggle_status_"):
                nowuid = d.replace("toggle_status_","")
                ok, msg = self.core.toggle_product_status(nowuid)
                q.answer(msg)
                if ok:
                    self.show_price_edit(q, nowuid)
                return
            elif d.startswith("profit_calc_"):
                self.show_profit_calculator(q, d.replace("profit_calc_","")); q.answer(); return
            elif d.startswith("set_price_"):
                parts = d.replace("set_price_","").split("_")
                nowuid, np = parts[0], float(parts[1])
                ok, msg = self.core.update_agent_price(nowuid, np)
                q.answer(msg)
                if ok:
                    self.show_price_edit(q, nowuid)
                return

            # 商品相关
            elif d.startswith("category_page_"):
                _, cat, p = d.split("_", 2)
                self.show_category_products(q, cat, int(p)); q.answer(); return
            elif d.startswith("category_"):
                self.show_category_products(q, d.replace("category_","")); q.answer(); return
            elif d.startswith("product_"):
                self.show_product_detail(q, d.replace("product_","")); q.answer(); return
            elif d.startswith("buy_"):
                self.handle_buy_product(q, d.replace("buy_","")); q.answer(); return
            elif d.startswith("confirm_buy_"):
                # ✅ 处理确认购买
                try:
                    parts = d.replace("confirm_buy_", "").split("_")
                    nowuid = parts[0]
                    qty = int(parts[1])
                    self.handle_confirm_buy(q, nowuid, qty, context)  # ← 加上 context
                    q.answer()
                except Exception as e:
                    logger.error(f"确认购买异常: {e}")
                    q.answer("参数错误", show_alert=True)
                return
                
                self.handle_confirm_buy(q, nowuid, qty)
                q.answer()
                return
            # 利润中心
            elif d == "profit_center":
                self.show_profit_center(q); q.answer(); return
            elif d == "profit_withdraw":
                self.start_withdrawal(q); q.answer(); return
            elif d == "profit_withdraw_list":
                self.show_withdrawal_list(q); q.answer(); return

            # 充值金额快捷按钮
            elif d.startswith("recharge_amount_"):
                uid = q.from_user.id
                try:
                    amt = Decimal(d.replace("recharge_amount_", "")).quantize(Decimal("0.01"))
                except Exception:
                    q.answer("金额格式错误", show_alert=True); return
                ok, msg, order = self.core.create_recharge_order(uid, amt)
                if not ok:
                    q.answer(msg, show_alert=True); return
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list"),
                     InlineKeyboardButton("❌ 取消订单", callback_data=f"recharge_cancel_{str(order['_id'])}")],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
                ])
                try:
                    self.core.send_plain_qr_with_caption(q.message.chat_id, order, kb)
                except Exception as e:
                    logger.warning(f"发送二维码caption失败(callback): {e}")
                    self.safe_edit_message(q, self._format_recharge_text(order), kb, parse_mode=ParseMode.HTML)
                q.answer("已生成识别金额，请按应付金额转账"); return

            elif d == "recharge_list":
                self.show_recharge_list(q); q.answer(); return

            # 订单取消
            elif d.startswith("recharge_cancel_"):
                oid = d.replace("recharge_cancel_", "")
                delete_mode = self.core.config.RECHARGE_DELETE_ON_CANCEL
                try:
                    order = self.core.config.recharge_orders.find_one({'_id': ObjectId(oid)})
                    res = self.core.config.recharge_orders.update_one(
                        {'_id': ObjectId(oid), 'status': 'pending'},
                        {'$set': {'status': 'canceled', 'canceled_time': datetime.utcnow()}}
                    )
                    if res.modified_count:
                        q.answer("已取消")
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📜 充值记录", callback_data="recharge_list"),
                             InlineKeyboardButton("🏠 返回主菜单", callback_data="back_main")]
                        ])
                        if delete_mode:
                            # 删除原消息后发新提示
                            try:
                                chat_id = q.message.chat_id
                                q.message.delete()
                                Bot(self.core.config.BOT_TOKEN).send_message(
                                    chat_id=chat_id,
                                    text="❌ 该充值订单已取消。\n请重新选择金额创建新的订单。",
                                    reply_markup=kb
                                )
                            except Exception as e_del:
                                logger.warning(f"删除订单消息失败: {e_del}")
                                # 回退编辑 caption
                                try:
                                    q.edit_message_caption(
                                        caption="❌ 该充值订单已取消。\n请重新选择金额创建新的订单。",
                                        reply_markup=kb,
                                        parse_mode=ParseMode.HTML
                                    )
                                except Exception as e_cap:
                                    logger.warning(f"编辑取消 caption 失败: {e_cap}")
                        else:
                            # 仅编辑原消息 caption
                            try:
                                q.edit_message_caption(
                                    caption="❌ 该充值订单已取消。\n请重新选择金额创建新的订单。",
                                    reply_markup=kb,
                                    parse_mode=ParseMode.HTML
                                )
                            except Exception as e_cap:
                                logger.warning(f"编辑取消 caption 失败: {e_cap}")
                                Bot(self.core.config.BOT_TOKEN).send_message(
                                    chat_id=q.message.chat_id,
                                    text="❌ 该充值订单已取消。\n请重新选择金额创建新的订单。",
                                    reply_markup=kb
                                )
                    else:
                        q.answer("无法取消（已过期/已支付/不存在）", show_alert=True)
                except Exception as e:
                    logger.warning(f"取消订单异常: {e}")
                    q.answer("取消失败", show_alert=True)
                return

            # 通用操作
            elif d == "no_action":
                q.answer(); return
            elif d.startswith("close "):
                try:
                    q.message.delete()
                except:
                    pass
                q.answer(); return

            else:
                self.safe_edit_message(q, "❓ 未知操作", [[InlineKeyboardButton("🏠 主菜单", callback_data="back_main")]], parse_mode=None)
                q.answer(); return

        except Exception as e:
            if "Message is not modified" in str(e):
                try:
                    q.answer("界面已是最新")
                except:
                    pass
            else:
                logger.warning(f"按钮处理异常: {e}")
                traceback.print_exc()
                try:
                    q.answer("操作异常", show_alert=True)
                except:
                    pass
                try:
                    q.edit_message_text("❌ 操作失败，请重试")
                except:
                    pass

    # ========== 文本消息状态处理 ==========
    def handle_text_message(self, update: Update, context: CallbackContext):
        """处理文本消息"""
        uid = update.effective_user.id
        message_text = update.message.text.strip() if update.message and update.message.text else ""
        
        # ✅ 优先检测国家/地区代码查询（带"+"号）
        if message_text and self._is_country_code_query(message_text):
            self.handle_country_code_search(update, context, message_text)
            return
        
        # ✅ 处理用户状态输入
        if uid not in self.user_states:
            return
        
        st = self.user_states[uid]
        try:
            if st.get('state') == 'waiting_quantity':
                # ✅ 处理购买数量输入
                self.handle_quantity_input(update, context)
                return
            
            elif st.get('state') == 'waiting_price':
                try:
                    new_price = float(update.message.text.strip())
                except:
                    update.message.reply_text("❌ 请输入有效的价格数字")
                    return
                nowuid = st['product_nowuid']
                op = st['original_price']
                if new_price < op:
                    update.message.reply_text(f"❌ 代理价格不能低于总部价格 {op} USDT")
                    return
                self.user_states.pop(uid, None)
                ok, msg = self.core.update_agent_price(nowuid, new_price)
                update.message.reply_text(("✅ " if ok else "❌ ") + msg)
                return
            
            elif st.get('state') == 'waiting_withdraw_amount':
                self.handle_withdraw_amount_input(update)
                return
            
            elif st.get('state') == 'waiting_withdraw_address':
                self.handle_withdraw_address_input(update)
                return
            
            elif st.get('state') == 'waiting_recharge_amount':
                txt = update.message.text.strip()
                try:
                    amt = Decimal(txt).quantize(Decimal("0.01"))
                except Exception:
                    update.message.reply_text("❌ 金额格式错误，请输入数字（例如 12 或 12.5）")
                    return
                self.handle_recharge_amount_input(update, amt)
                return
        
        except Exception as e:
            logger.error(f"文本处理异常: {e}")
            update.message.reply_text("❌ 处理异常，请重试")
            if uid in self.user_states:
                self.user_states.pop(uid, None)

    # ========== 广告频道消息处理 ==========
    def handle_ad_channel_message(self, update: Update, context: CallbackContext):
        """
        监听广告频道的消息，自动推送广告到所有代理用户的私聊
        
        功能：
        1. 监听 AGENT_AD_CHANNEL_ID 的消息
        2. 检查 AGENT_AD_DM_ENABLED 是否启用
        3. 提取消息文本/caption
        4. 包装为私聊模板（📢 最新公告）
        5. 调用 broadcast_ad_to_agent_users 推送
        """
        try:
            # 处理频道帖子和普通消息
            message = update.message or update.channel_post
            
            if not message or not message.chat:
                return
            
            chat_id = message.chat.id
            
            # 如果功能未启用，直接返回
            if not self.core.config.AGENT_AD_DM_ENABLED:
                logger.debug(f"🔍 广告推送: 功能未启用 (chat_id={chat_id}, AGENT_AD_DM_ENABLED=0)")
                return
            
            # 如果未配置广告频道ID，直接返回
            if not self.core.config.AGENT_AD_CHANNEL_ID:
                logger.debug(f"🔍 广告推送: 未配置广告频道ID (chat_id={chat_id}, AGENT_AD_CHANNEL_ID=未设置)")
                return
            
            # 将配置中的 chat_id 转换为整数进行比较
            try:
                ad_channel_id = int(self.core.config.AGENT_AD_CHANNEL_ID)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ AGENT_AD_CHANNEL_ID 格式错误: {self.core.config.AGENT_AD_CHANNEL_ID}")
                return
            
            # 检查是否来自广告频道
            logger.debug(f"🔍 广告推送: 比较 chat_id={chat_id}, ad_channel_id={ad_channel_id}, 匹配={chat_id == ad_channel_id}")
            if chat_id != ad_channel_id:
                return
            
            logger.info(f"📢 检测到广告频道消息 (chat_id={chat_id})")
            
            # 提取消息内容
            message_text = message.text or message.caption or ""
            
            if not message_text:
                logger.warning("⚠️ 广告消息无文本内容，跳过推送")
                return
            
            # 包装消息为私聊模板
            wrapped_text = f"<b>📢 最新公告</b>\n\n{message_text}"
            
            logger.info(f"🚀 开始广播广告消息: {message_text[:50]}...")
            
            # 调用核心广播方法
            success_count = self.core.broadcast_ad_to_agent_users(wrapped_text, parse_mode=ParseMode.HTML)
            
            logger.info(f"✅ 广告推送完成: 成功通知 {success_count} 个用户")
            
            # 发送广播完成通知到广告通知群（独立配置）
            if self.core.config.AGENT_AD_NOTIFY_CHAT_ID and success_count > 0:
                try:
                    from datetime import datetime
                    now_beijing = datetime.utcnow() + timedelta(hours=8)
                    
                    # 获取用户总数用于计算成功率
                    user_collection = self.core.config.get_agent_user_collection()
                    query = {}
                    if self.core.config.AGENT_AD_DM_ACTIVE_DAYS > 0:
                        cutoff_date = datetime.now() - timedelta(days=self.core.config.AGENT_AD_DM_ACTIVE_DAYS)
                        cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
                        query['last_active'] = {'$gte': cutoff_str}
                    total_users = user_collection.count_documents(query)
                    
                    # 考虑最大发送限制
                    max_per_run = self.core.config.AGENT_AD_DM_MAX_PER_RUN
                    if max_per_run > 0 and total_users > max_per_run:
                        total_users = max_per_run
                    
                    success_rate = (success_count / total_users * 100) if total_users > 0 else 0
                    
                    notification_text = (
                        f"📢 <b>广告推送完成报告</b>\n\n"
                        f"🏢 代理ID：<code>{self.core._h(self.core.config.AGENT_BOT_ID)}</code>\n"
                        f"🤖 代理名称：{self.core._h(self.core.config.AGENT_NAME)}\n"
                        f"✅ 成功发送：<b>{success_count}</b> / {total_users} 用户\n"
                        f"📊 成功率：<b>{success_rate:.1f}%</b>\n"
                        f"⏰ 完成时间：{now_beijing.strftime('%Y-%m-%d %H:%M:%S')} (北京时间)\n\n"
                        f"📝 广告内容（前100字符）：\n<code>{self.core._h(message_text[:100])}...</code>"
                    )
                    
                    Bot(self.core.config.BOT_TOKEN).send_message(
                        chat_id=self.core.config.AGENT_AD_NOTIFY_CHAT_ID,
                        text=notification_text,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"📤 已发送广播完成通知到广告通知群: {self.core.config.AGENT_AD_NOTIFY_CHAT_ID}")
                except Exception as notify_err:
                    logger.warning(f"⚠️ 发送广播完成通知失败: {notify_err}")
            
        except Exception as e:
            logger.error(f"❌ 处理广告频道消息异常: {e}")
            traceback.print_exc()

    # ========== 补货通知镜像功能 ==========
    def handle_headquarters_message(self, update: Update, context: CallbackContext):
        """
        监听总部通知群的消息，自动转发补货通知到代理补货通知群
        
        功能：
        1. 监听 HEADQUARTERS_NOTIFY_CHAT_ID 的消息
        2. 匹配补货关键词
        3. 使用 copy_message 转发消息（保留格式、媒体、caption）
        4. 如果 copy_message 失败，回退到 send_message
        5. 防止循环：只处理 chat.id == HEADQUARTERS_NOTIFY_CHAT_ID 的消息
        6. 可选：重写按钮指向代理机器人（默认关闭）
        """
        try:
            # ✅ 处理频道帖子和普通消息
            # Telegram channels send updates as channel_post, not message
            message = update.message or update.channel_post
            
            if not message or not message.chat:
                logger.debug("⚠️ handle_headquarters_message: 无消息或聊天对象")
                return
            
            chat_id = message.chat.id
            chat_type = message.chat.type
            
            # ✅ 调试日志：记录所有接收到的群组/频道消息
            logger.info(f"🔍 收到群组/频道消息: chat_id={chat_id}, chat_type={chat_type}, title={message.chat.title}")
            
            # 检查是否来自总部通知群
            if not self.core.config.HEADQUARTERS_NOTIFY_CHAT_ID:
                logger.warning("⚠️ HEADQUARTERS_NOTIFY_CHAT_ID 未配置")
                return
            
            # 将配置中的 chat_id 转换为整数进行比较
            try:
                hq_chat_id = int(self.core.config.HEADQUARTERS_NOTIFY_CHAT_ID)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ HEADQUARTERS_NOTIFY_CHAT_ID 格式错误: {self.core.config.HEADQUARTERS_NOTIFY_CHAT_ID}")
                return
            
            logger.debug(f"🔍 比较: chat_id={chat_id}, hq_chat_id={hq_chat_id}, 匹配={chat_id == hq_chat_id}")
            
            if chat_id != hq_chat_id:
                logger.debug(f"⚠️ 消息不是来自总部通知群（来自 {chat_id}，期望 {hq_chat_id}）")
                return
            
            # 检查是否有补货通知目标群
            if not self.core.config.AGENT_RESTOCK_NOTIFY_CHAT_ID:
                logger.warning("⚠️ AGENT_RESTOCK_NOTIFY_CHAT_ID 未配置，无法转发补货通知")
                return
            
            logger.info(f"✅ 消息来自总部通知群 {hq_chat_id}")
            
            # 获取消息内容用于关键词匹配
            message_text = message.text or message.caption or ""
            
            logger.debug(f"🔍 消息文本: {message_text[:100]}...")
            logger.debug(f"🔍 配置的关键词: {self.core.config.RESTOCK_KEYWORDS}")
            
            # 检查是否包含补货关键词
            is_restock = False
            matched_keyword = None
            for keyword in self.core.config.RESTOCK_KEYWORDS:
                if keyword and keyword.lower() in message_text.lower():
                    is_restock = True
                    matched_keyword = keyword
                    break
            
            if not is_restock:
                logger.debug(f"⚠️ 消息不包含补货关键词，跳过转发")
                return
            
            logger.info(f"🔔 检测到补货通知（关键词: {matched_keyword}）: {message_text[:50]}...")
            
            target_chat_id = self.core.config.AGENT_RESTOCK_NOTIFY_CHAT_ID
            
            # ✅ 决定是否重写按钮
            enable_button_rewrite = self.core.config.HQ_RESTOCK_REWRITE_BUTTONS
            
            if enable_button_rewrite:
                logger.info("🔄 按钮重写已启用，将发送带重写按钮的新消息")
                # 当启用按钮重写时，发送新消息而不是使用 copy_message
                try:
                    # 获取机器人用户名用于构建按钮URL
                    bot_info = context.bot.get_me()
                    bot_username = bot_info.username
                    
                    # ✅ 尝试从原始消息中提取商品ID（nowuid）
                    nowuid = None
                    
                    # 方法1：从原始消息的按钮中提取
                    if message.reply_markup and hasattr(message.reply_markup, 'inline_keyboard'):
                        for row in message.reply_markup.inline_keyboard:
                            for button in row:
                                if button.url and 'start=' in button.url:
                                    # 从URL中提取参数，例如: https://t.me/bot?start=buy_123456
                                    try:
                                        start_param = button.url.split('start=')[1].split('&')[0]
                                        if start_param.startswith('buy_'):
                                            nowuid = start_param.replace('buy_', '')
                                            logger.info(f"🔍 从按钮URL提取到商品ID: {nowuid}")
                                            break
                                    except:
                                        pass
                                elif button.callback_data and button.callback_data.startswith('gmsp '):
                                    # 从callback_data中提取，例如: gmsp 123456
                                    try:
                                        nowuid = button.callback_data.replace('gmsp ', '').strip()
                                        logger.info(f"🔍 从按钮callback提取到商品ID: {nowuid}")
                                        break
                                    except:
                                        pass
                            if nowuid:
                                break
                    
                    # 方法2：从消息文本中使用正则表达式提取（补货通知通常包含商品名称或ID）
                    if not nowuid and message_text:
                        import re
                        # 尝试匹配常见的ID格式
                        id_patterns = [
                            r'ID[：:]\s*([a-zA-Z0-9]+)',
                            r'商品ID[：:]\s*([a-zA-Z0-9]+)',
                            r'nowuid[：:]\s*([a-zA-Z0-9]+)',
                        ]
                        for pattern in id_patterns:
                            match = re.search(pattern, message_text, re.IGNORECASE)
                            if match:
                                nowuid = match.group(1)
                                logger.info(f"🔍 从消息文本提取到商品ID: {nowuid}")
                                break
                    
                    # 构建重写后的按钮
                    # ✅ 优先使用深度链接，如果没有用户名则使用callback按钮
                    if bot_username:
                        if nowuid:
                            # 如果提取到商品ID，使用product_深度链接
                            keyboard = [[
                                InlineKeyboardButton("🛒 购买商品", url=f"https://t.me/{bot_username}?start=product_{nowuid}")
                            ]]
                            logger.info(f"🔗 使用商品深度链接按钮: https://t.me/{bot_username}?start=product_{nowuid}")
                        else:
                            # 否则使用通用的restock链接
                            keyboard = [[
                                InlineKeyboardButton("🛒 购买商品", url=f"https://t.me/{bot_username}?start=restock")
                            ]]
                            logger.info(f"🔗 使用通用补货深度链接按钮: https://t.me/{bot_username}?start=restock")
                    else:
                        if nowuid:
                            keyboard = [[
                                InlineKeyboardButton("🛒 购买商品", callback_data=f"product_{nowuid}")
                            ]]
                        else:
                            keyboard = [[
                                InlineKeyboardButton("🛒 购买商品", callback_data="products")
                            ]]
                        logger.warning("⚠️ 未获取到机器人用户名，使用callback按钮作为回退方案")
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # 根据消息类型发送带有重写按钮的新消息
                    if message.photo:
                        photo = message.photo[-1]  # 取最大尺寸
                        result = context.bot.send_photo(
                            chat_id=target_chat_id,
                            photo=photo.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None,
                            reply_markup=reply_markup
                        )
                        logger.info(f"✅ 补货通知(图片+重写按钮)已发送到 {target_chat_id} (message_id: {result.message_id})")
                    elif message.video:
                        result = context.bot.send_video(
                            chat_id=target_chat_id,
                            video=message.video.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None,
                            reply_markup=reply_markup
                        )
                        logger.info(f"✅ 补货通知(视频+重写按钮)已发送到 {target_chat_id} (message_id: {result.message_id})")
                    elif message.document:
                        result = context.bot.send_document(
                            chat_id=target_chat_id,
                            document=message.document.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None,
                            reply_markup=reply_markup
                        )
                        logger.info(f"✅ 补货通知(文档+重写按钮)已发送到 {target_chat_id} (message_id: {result.message_id})")
                    else:
                        # 纯文本消息
                        if message_text:
                            result = context.bot.send_message(
                                chat_id=target_chat_id,
                                text=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                            logger.info(f"✅ 补货通知(文本+重写按钮)已发送到 {target_chat_id} (message_id: {result.message_id})")
                        else:
                            logger.warning("⚠️ 消息无文本内容，跳过发送")
                    
                    return
                    
                except Exception as rewrite_err:
                    logger.error(f"❌ 发送带重写按钮的消息失败: {rewrite_err}")
                    traceback.print_exc()
                    return
            
            else:
                logger.info("📋 按钮重写未启用，使用 copy_message 转发原始消息")
                # 当未启用按钮重写时，使用 copy_message 保留原样
                try:
                    result = context.bot.copy_message(
                        chat_id=target_chat_id,
                        from_chat_id=chat_id,
                        message_id=message.message_id
                    )
                    
                    logger.info(f"✅ 补货通知已原样镜像到 {target_chat_id} (message_id: {result.message_id})")
                    return
                    
                except Exception as copy_err:
                    logger.warning(f"⚠️ copy_message 失败（可能是权限问题）: {copy_err}")
                    logger.info("🔄 尝试使用 send_message 回退方案...")
                
                # 回退方案：使用 send_message（无按钮重写）
                try:
                    if message.photo:
                        photo = message.photo[-1]  # 取最大尺寸
                        context.bot.send_photo(
                            chat_id=target_chat_id,
                            photo=photo.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None
                        )
                    elif message.video:
                        context.bot.send_video(
                            chat_id=target_chat_id,
                            video=message.video.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None
                        )
                    elif message.document:
                        context.bot.send_document(
                            chat_id=target_chat_id,
                            document=message.document.file_id,
                            caption=message_text or None,
                            parse_mode=ParseMode.HTML if message_text else None
                        )
                    else:
                        if message_text:
                            context.bot.send_message(
                                chat_id=target_chat_id,
                                text=message_text,
                                parse_mode=ParseMode.HTML
                            )
                    
                    logger.info(f"✅ 补货通知已通过回退方案发送到 {target_chat_id}")
                    
                except Exception as send_err:
                    logger.error(f"❌ 回退方案也失败: {send_err}")
        
        except Exception as e:
            logger.error(f"❌ 处理总部消息异常: {e}")
            traceback.print_exc()


class AgentBot:
    """主入口（自动轮询充值）"""

    def __init__(self, token: str):
        self.config = AgentBotConfig()
        self.core = AgentBotCore(self.config)
        self.handlers = AgentBotHandlers(self.core)
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self._watch_thread = None
        self._watch_stop_flag = False

    def start_headquarters_product_watch(self):
        """启动总部商品 Change Stream 监听线程"""
        
        def _watch_loop():
            """Change Stream 监听循环"""
            logger.info("🔍 启动总部商品 Change Stream 监听线程...")
            fail_count = 0
            max_fails = 5
            
            while not self._watch_stop_flag:
                try:
                    # 尝试使用 Change Streams
                    logger.info("📡 尝试连接 MongoDB Change Streams...")
                    with self.config.ejfl.watch([
                        {'$match': {
                            'operationType': {'$in': ['insert', 'update', 'replace']}
                        }}
                    ]) as stream:
                        logger.info("✅ MongoDB Change Streams 连接成功，开始监听...")
                        fail_count = 0  # 重置失败计数
                        
                        for change in stream:
                            if self._watch_stop_flag:
                                break
                            
                            try:
                                op_type = change.get('operationType')
                                doc_key = change.get('documentKey', {}).get('_id')
                                logger.info(f"📢 检测到商品变更: {op_type} (doc_id: {doc_key})")
                                
                                # 触发同步
                                synced = self.core.auto_sync_new_products()
                                if synced > 0:
                                    logger.info(f"✅ Change Stream 触发同步成功: {synced} 个商品")
                            except Exception as e:
                                logger.warning(f"处理 Change Stream 事件异常: {e}")
                        
                except Exception as e:
                    fail_count += 1
                    error_msg = str(e).lower()
                    
                    # 检查是否是副本集未配置错误
                    if 'repl' in error_msg or 'replica' in error_msg or 'not supported' in error_msg:
                        logger.warning(f"⚠️ MongoDB Change Streams 不可用（可能未配置副本集）: {e}")
                        logger.info("💡 已自动回退到轮询模式，Change Stream 监听线程退出")
                        break
                    else:
                        logger.warning(f"❌ Change Stream 连接失败 ({fail_count}/{max_fails}): {e}")
                    
                    if fail_count >= max_fails:
                        logger.warning(f"⚠️ Change Stream 累计失败 {max_fails} 次，退出监听线程，依赖轮询兜底")
                        break
                    
                    # 等待后重试
                    if not self._watch_stop_flag:
                        time.sleep(5)
            
            logger.info("🛑 Change Stream 监听线程已退出")
        
        if self.config.AGENT_ENABLE_PRODUCT_WATCH:
            self._watch_thread = threading.Thread(target=_watch_loop, daemon=True, name="ProductWatch")
            self._watch_thread.start()
            logger.info("✅ Change Stream 监听线程已启动")
        else:
            logger.info("ℹ️ Change Stream 监听已禁用（环境变量 AGENT_ENABLE_PRODUCT_WATCH=0）")

    def _job_auto_product_poll(self, context: CallbackContext):
        """定时轮询商品同步任务（兜底方案）"""
        try:
            synced = self.core.auto_sync_new_products()
            if synced > 0:
                logger.info(f"✅ 轮询触发商品同步: {synced} 个商品")
        except Exception as e:
            logger.warning(f"轮询同步任务异常: {e}")

    def setup_handlers(self):
        self.dispatcher.add_handler(CommandHandler("start", self.handlers.start_command))
        self.dispatcher.add_handler(CommandHandler("reload_admins", self.handlers.reload_admins_command))
        self.dispatcher.add_handler(CallbackQueryHandler(self.handlers.button_callback))
        
        # ✅ 创建组合处理器，同时处理总部通知和广告频道消息
        def combined_channel_handler(update: Update, context: CallbackContext):
            """组合处理器：同时处理补货通知镜像和广告推送"""
            # 先尝试处理广告频道消息
            self.handlers.handle_ad_channel_message(update, context)
            # 再处理总部通知消息
            self.handlers.handle_headquarters_message(update, context)
        
        # ✅ 群组/频道消息处理（补货通知镜像 + 广告推送）- 放在私聊处理器之前
        # 使用更宽松的过滤器，让handler内部进行chat_id检查
        # 处理普通消息（群组、超级群组）
        self.dispatcher.add_handler(MessageHandler(
            (Filters.text | Filters.photo | Filters.video | Filters.document) & 
            ~Filters.chat_type.private,  # 任何非私聊的消息（群组、超级群组、频道）
            combined_channel_handler
        ))
        
        # ✅ 处理频道帖子（channel_post）
        # Telegram频道的消息以channel_post形式发送，需要单独处理
        from telegram.ext import Filters as TelegramFilters
        self.dispatcher.add_handler(MessageHandler(
            (Filters.text | Filters.photo | Filters.video | Filters.document) & 
            Filters.update.channel_post,  # 频道帖子
            combined_channel_handler
        ))
        
        # ✅ 私聊文本消息处理（用户输入处理）
        self.dispatcher.add_handler(MessageHandler(
            Filters.text & ~Filters.command & Filters.chat_type.private, 
            self.handlers.handle_text_message
        ))
        
        logger.info("✅ 处理器设置完成")

        # ✅ 充值自动校验任务
        try:
            self.updater.job_queue.run_repeating(
                self._job_auto_recharge_check,
                interval=self.config.RECHARGE_POLL_INTERVAL_SECONDS,
                first=5
            )
            logger.info(f"✅ 已启动充值自动校验任务（间隔 {self.config.RECHARGE_POLL_INTERVAL_SECONDS}s）")
        except Exception as e:
            logger.warning(f"启动自动校验任务失败: {e}")
        
        # ✅ 商品同步轮询任务（兜底方案）
        try:
            self.updater.job_queue.run_repeating(
                self._job_auto_product_poll,
                interval=self.config.PRODUCT_SYNC_POLL_SECONDS,
                first=10  # 首次延迟10秒启动
            )
            logger.info(f"✅ 已启动商品同步轮询任务（间隔 {self.config.PRODUCT_SYNC_POLL_SECONDS}s，兜底方案）")
        except Exception as e:
            logger.warning(f"启动商品同步轮询任务失败: {e}")

    def _job_auto_recharge_check(self, context: CallbackContext):
        try:
            self.core.poll_and_auto_settle_recharges(max_orders=80)
        except Exception as e:
            logger.warning(f"自动校验任务异常: {e}")

    def run(self):
        try:
            self.setup_handlers()
            
            # ✅ 启动 Change Stream 监听线程（如果启用）
            self.start_headquarters_product_watch()
            
            self.updater.start_polling()
            logger.info("🚀 机器人启动成功，开始监听消息...")
            self.updater.idle()
        except KeyboardInterrupt:
            logger.info("👋 收到退出信号，正在停止...")
            self._watch_stop_flag = True
            if self._watch_thread and self._watch_thread.is_alive():
                self._watch_thread.join(timeout=3)
            raise
        except Exception as e:
            logger.error(f"❌ 机器人运行失败: {e}")
            self._watch_stop_flag = True
            raise


def main():
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("--env"):
        token = sys.argv[1]
    else:
        token = os.getenv("BOT_TOKEN")
    if not token:
        print("用法: python agent_bot.py <BOT_TOKEN> [--env yourenvfile]")
        sys.exit(1)
    print("🤖 华南代理机器人（统一通知 + + 10分钟有效 + 取消修复版）")
    print(f"📡 Token: {token[:10]}...")
    print(f"⏰ 启动(北京时间): {(datetime.utcnow()+timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    try:
        bot = AgentBot(token)
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 机器人停止运行")
    except Exception as e:
        print(f"\n❌ 机器人运行错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
