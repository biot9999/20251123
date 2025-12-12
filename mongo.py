import json
import random
import re
import pymongo
from pymongo.collection import Collection
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv
import os
import threading

# 加载环境变量
load_dotenv()

# ✅ 初始化日志系统
def init_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(f"{log_dir}/init.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logging.info("📌 日志系统初始化完成")

init_logging()

# ✅ 环境变量配置集中管理
class Config:
    # MongoDB 配置
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/')
    MONGO_DB_BOT = os.getenv('MONGO_DB_BOT', '9hao1bot')
    MONGO_DB_XCHP = os.getenv('MONGO_DB_XCHP', '9hao1bot')
    MONGO_DB_MAIN = os.getenv('MONGO_DB_MAIN', 'qukuailian')
    
    # 客服联系方式
    CUSTOMER_SERVICE = os.getenv('CUSTOMER_SERVICE', '@o9eth')
    OFFICIAL_CHANNEL = os.getenv('OFFICIAL_CHANNEL', '@o9eth')
    RESTOCK_GROUP = os.getenv('RESTOCK_GROUP', 'https://t.me/+EeTF1qOe_MoyMzQ0')
    
    # Bot 配置
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_USERNAME = os.getenv('BOT_USERNAME', '9hao1bot')
    NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "0"))
    
    # 时间配置
    STOCK_NOTIFICATION_DELAY = int(os.getenv('STOCK_NOTIFICATION_DELAY', '3'))
    MESSAGE_DELETE_DELAY = int(os.getenv('MESSAGE_DELETE_DELAY', '3'))
    
    # 验证关键配置
    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ BOT_TOKEN 环境变量未设置")
        if cls.NOTIFY_CHANNEL_ID == 0:
            logging.warning("⚠️ NOTIFY_CHANNEL_ID 未设置，库存通知可能无法正常工作")

# 验证配置
Config.validate()

# ✅ 使用配置类的值
MONGO_URI = Config.MONGO_URI
MONGO_DB_BOT = Config.MONGO_DB_BOT
MONGO_DB_XCHP = Config.MONGO_DB_XCHP
MONGO_DB_MAIN = Config.MONGO_DB_MAIN
CUSTOMER_SERVICE = Config.CUSTOMER_SERVICE
OFFICIAL_CHANNEL = Config.OFFICIAL_CHANNEL
RESTOCK_GROUP = Config.RESTOCK_GROUP
BOT_TOKEN = Config.BOT_TOKEN
NOTIFY_CHANNEL_ID = Config.NOTIFY_CHANNEL_ID
STOCK_NOTIFICATION_DELAY = Config.STOCK_NOTIFICATION_DELAY
BOT_USERNAME = Config.BOT_USERNAME

# ✅ 数据库连接和集合管理优化
class DatabaseManager:
    def __init__(self):
        self.client = pymongo.MongoClient(MONGO_URI)
        
        # 主数据库
        self.main_db = self.client[MONGO_DB_MAIN]
        self.qukuai = self.main_db['qukuai']
        
        # 机器人数据库
        self.bot_db = self.client[MONGO_DB_BOT]
        self._init_collections()
        
        logging.info("✅ 数据库连接初始化完成")
    
    def _init_collections(self):
        """初始化所有集合"""
        self.user = self.bot_db['user']
        self.shangtext = self.bot_db['shangtext']
        self.get_key = self.bot_db['get_key']
        self.topup = self.bot_db['topup']
        self.get_kehuduan = self.bot_db['get_kehuduan']
        self.shiyong = self.bot_db['shiyong']
        self.user_log = self.bot_db['user_log']
        self.fenlei = self.bot_db['fenlei']
        self.ejfl = self.bot_db['ejfl']
        self.hb = self.bot_db['hb']
        self.xyh = self.bot_db['xyh']
        self.gmjlu = self.bot_db['gmjlu']
        self.fyb = self.bot_db['fyb']
        self.sftw = self.bot_db['sftw']
        self.hongbao = self.bot_db['hongbao']
        self.qb = self.bot_db['qb']
        self.zhuanz = self.bot_db['zhuanz']
        self.withdrawal_requests = self.bot_db['withdrawal_requests']
    
    def close(self):
        """关闭数据库连接"""
        self.client.close()
        logging.info("✅ 数据库连接已关闭")

# 初始化数据库管理器
db_manager = DatabaseManager()

# ✅ 为了向后兼容，保留原有变量名
teleclient = db_manager.client
main_db = db_manager.main_db
qukuai = db_manager.qukuai
bot_db = db_manager.bot_db
user = db_manager.user
shangtext = db_manager.shangtext
get_key = db_manager.get_key
topup = db_manager.topup
get_kehuduan = db_manager.get_kehuduan
shiyong = db_manager.shiyong
user_log = db_manager.user_log
fenlei = db_manager.fenlei
ejfl = db_manager.ejfl
hb = db_manager.hb
xyh = db_manager.xyh
gmjlu = db_manager.gmjlu
fyb = db_manager.fyb
sftw = db_manager.sftw
hongbao = db_manager.hongbao
qb = db_manager.qb
zhuanz = db_manager.zhuanz
withdrawal_requests = db_manager.withdrawal_requests

# ✅ 库存通知管理优化
class StockNotificationManager:
    def __init__(self):
        self.notify_cache = {}
        self.last_notify_time = {}
        self.notification_lock = threading.Lock()
        self.bot_instance = None
        self.notification_timer = None  # Single timer for batched notifications
    
    def get_bot(self):
        """获取或创建 Bot 实例"""
        if self.bot_instance is None:
            self.bot_instance = Bot(token=BOT_TOKEN)
        return self.bot_instance
    
    def add_stock_notification(self, nowuid: str, projectname: str):
        """添加库存通知"""
        with self.notification_lock:
            if nowuid not in self.notify_cache:
                self.notify_cache[nowuid] = {'projectname': projectname, 'count': 1}
            else:
                self.notify_cache[nowuid]['count'] += 1
    
    def send_notification(self, nowuid: str, projectname: str, price: float, stock: int, count: int):
        """发送单个商品的库存通知"""
        try:
            if count <= 0:
                logging.info(f"ℹ️ 补货数为0，跳过通知：nowuid={nowuid}")
                return
            
            # 分离一级分类和二级分类名称
            if "/" in projectname:
                parent_name, product_name = projectname.split("/", 1)
            else:
                parent_name = "未分类"
                product_name = projectname
            
            text = f"""
<b>💭💭 库存更新💭💭</b>

<b>{parent_name} /{product_name}</b>

<b>💰 商品价格：{price:.2f} U</b>

<b>🆕 新增库存：{count} 个</b>

<b>📊 剩余库存：{stock} 个</b>

<b>🛒 点击下方按钮快速购买</b>
            """.strip()

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 购买商品", url=f"https://t.me/{BOT_USERNAME}?start=buy_{nowuid}")]
            ])
            
            bot = self.get_bot()
            bot.send_message(
                chat_id=NOTIFY_CHANNEL_ID, 
                text=text, 
                parse_mode='HTML', 
                reply_markup=keyboard
            )
            logging.info(f"✅ 补货通知已发送：{projectname} (新增{count}个)")
        except Exception as e:
            logging.error(f"❌ 推送失败：{e}")
    
    def send_batched_notifications(self):
        """发送批量库存通知 - 合并为一条消息"""
        with self.notification_lock:
            if not self.notify_cache:
                return
            
            notifications_to_send = self.notify_cache.copy()
            self.notify_cache.clear()
        
        # 如果只有一个商品，使用原来的单条通知格式
        if len(notifications_to_send) == 1:
            nowuid, info = list(notifications_to_send.items())[0]
            try:
                product = ejfl.find_one({'nowuid': nowuid})
                if not product:
                    logging.warning(f"❌ 未找到商品信息：nowuid={nowuid}")
                    return
                
                uid = product.get('uid')
                parent_category = fenlei.find_one({'uid': uid})
                parent_name = parent_category['projectname'] if parent_category else "未知分类"
                product_name = f"{parent_name}/{product['projectname']}"
                price = float(product.get('money', 0))
                stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
                
                self.send_notification(nowuid, product_name, price, stock, info['count'])
                logging.info(f"📢 发送单商品通知：{product_name} (新增{info['count']}个)")
            except Exception as e:
                logging.error(f"❌ 发送库存通知失败：nowuid={nowuid}, error={e}")
            return
        
        # 多个商品：合并为一条总通知
        try:
            total_count = sum(info['count'] for info in notifications_to_send.values())
            product_details = []
            
            for nowuid, info in notifications_to_send.items():
                try:
                    product = ejfl.find_one({'nowuid': nowuid})
                    if not product:
                        continue
                    
                    uid = product.get('uid')
                    parent_category = fenlei.find_one({'uid': uid})
                    parent_name = parent_category['projectname'] if parent_category else "未知分类"
                    product_name = f"{parent_name}/{product['projectname']}"
                    price = float(product.get('money', 0))
                    stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
                    
                    product_details.append({
                        'nowuid': nowuid,
                        'name': product_name,
                        'price': price,
                        'count': info['count'],
                        'stock': stock
                    })
                except Exception as e:
                    logging.error(f"❌ 处理商品信息失败：nowuid={nowuid}, error={e}")
            
            if not product_details:
                logging.warning("⚠️ 没有有效的商品信息，跳过通知")
                return
            
            # 构建合并通知消息
            text = f"<b>💭💭 库存更新💭💭</b>\n\n"
            text += f"<b>🆕 本次新增库存总数：{total_count} 个</b>\n\n"
            text += f"<b>📦 涉及商品数量：{len(product_details)} 个</b>\n\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            # 按照新增数量排序，优先显示新增最多的
            product_details.sort(key=lambda x: x['count'], reverse=True)
            
            for idx, detail in enumerate(product_details, 1):
                text += f"<b>{idx}. {detail['name']}</b>\n"
                text += f"   💰 价格：{detail['price']:.2f} U\n"
                text += f"   🆕 新增：{detail['count']} 个\n"
                text += f"   📊 库存：{detail['stock']} 个\n\n"
            
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "<b>🛒 点击下方按钮查看商品列表</b>"
            
            # 使用第一个商品的购买链接（或者可以链接到商品列表）
            first_nowuid = product_details[0]['nowuid']
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 查看商品列表", url=f"https://t.me/{BOT_USERNAME}")]
            ])
            
            bot = self.get_bot()
            bot.send_message(
                chat_id=NOTIFY_CHANNEL_ID,
                text=text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            logging.info(f"✅ 批量库存通知已发送：总计{total_count}个商品，涉及{len(product_details)}个商品类别")
            
        except Exception as e:
            logging.error(f"❌ 发送批量通知失败：{e}")
            import traceback
            traceback.print_exc()
    
    def schedule_notification(self, nowuid: str, projectname: str):
        """安排延迟通知 - 使用单一计时器防止重复通知"""
        self.add_stock_notification(nowuid, projectname)
        
        with self.notification_lock:
            # 取消现有的计时器（如果存在）
            if self.notification_timer is not None:
                self.notification_timer.cancel()
            
            # 创建新的计时器
            self.notification_timer = threading.Timer(
                STOCK_NOTIFICATION_DELAY,
                self._execute_batched_notifications
            )
            self.notification_timer.daemon = True
            self.notification_timer.start()
        
        logging.info(f"🔔 已安排批量库存通知延迟任务：{projectname} (nowuid={nowuid})")
    
    def _execute_batched_notifications(self):
        """执行批量通知（私有方法）"""
        try:
            self.send_batched_notifications()
        except Exception as e:
            logging.error(f"❌ 延迟通知失败：{e}")
        finally:
            with self.notification_lock:
                self.notification_timer = None

# 初始化库存通知管理器
stock_manager = StockNotificationManager()

# ✅ 为了向后兼容，保留原有变量和函数
stock_notify_cache = stock_manager.notify_cache
last_notify_time = stock_manager.last_notify_time
notification_lock = stock_manager.notification_lock

def send_stock_notification(bot: Bot, channel_id: int, projectname: str, price: float, stock: int, nowuid: str, bot_username: str = None):
    """向后兼容的库存通知函数"""
    if bot_username is None:
        bot_username = BOT_USERNAME
    
    count = stock_notify_cache.get(nowuid, {}).get('count', 0)
    stock_manager.send_notification(nowuid, projectname, price, stock, count)

def send_batched_stock_notifications(bot: Bot, channel_id: int):
    """向后兼容的批量通知函数"""
    stock_manager.send_batched_notifications()

def shang_text(projectname, text):
    """统一的商店文本插入函数"""
    try:
        shangtext.insert_one({'projectname': projectname, 'text': text})
        logging.info(f"✅ 插入 shangtext：{projectname}")
    except Exception as e:
        logging.error(f"❌ 插入 shangtext 失败：{projectname} - {e}")

def sifatuwen(bot_id, projectname, text, file_id, key_text, keyboard, send_type):
    """司法图文插入函数"""
    try:
        sftw.insert_one({
            'bot_id': bot_id,
            'projectname': projectname,
            'text': text,
            'file_id': file_id,
            'key_text': key_text,
            'keyboard': keyboard,
            'send_type': send_type,
            'state': 1,
            'entities': b'\x80\x03]q\x00.'
        })
        logging.info(f"✅ 插入司法图文：{projectname}")
    except Exception as e:
        logging.error(f"❌ 插入司法图文失败：{projectname} - {e}")

def fanyibao(projectname, text, fanyi):
    """翻译包插入函数"""
    try:
        fyb.insert_one({
            'projectname': projectname,
            'text': text,
            'fanyi': fanyi
        })
        logging.info(f"✅ 插入翻译包：{projectname}")
    except Exception as e:
        logging.error(f"❌ 插入翻译包失败：{projectname} - {e}")

def goumaijilua(leixing, bianhao, user_id, projectname, text, ts, timer, count):
    """购买记录插入函数"""
    try:
        gmjlu.insert_one({
            'leixing': leixing,
            'bianhao': bianhao,
            'user_id': user_id,
            'projectname': projectname,
            'text': text,
            'ts': ts,
            'timer': timer,
            'count': count   # ✅ 记录实际数量
        })
        logging.info(f"✅ 插入购买记录：{user_id} - {projectname}")
    except Exception as e:
        logging.error(f"❌ 插入购买记录失败：{user_id} - {projectname} - {e}")

def xieyihaobaocun(uid, nowuid, hbid, projectname, timer):
    """协议号保存函数"""
    try:
        xyh.insert_one({
            'uid': uid,
            'nowuid': nowuid,
            'hbid': hbid,
            'projectname': projectname,
            'state': 0,
            'timer': timer
        })
        logging.info(f"✅ 保存协议号：{projectname} (nowuid={nowuid})")
    except Exception as e:
        logging.error(f"❌ 保存协议号失败：{projectname} - {e}")


def shangchuanhaobao(leixing, uid, nowuid, hbid, projectname, timer, remark=''):
    """优化的商品上架函数"""
    try:
        # 插入商品数据
        hb.insert_one({
            'leixing': leixing,
            'uid': uid,
            'nowuid': nowuid,
            'hbid': hbid,
            'projectname': projectname,
            'state': 0,
            'timer': timer,
            'remark': remark
        })
        logging.info(f"✅ 上架商品成功：{projectname} (nowuid={nowuid})")

        # ✅ 使用优化的库存通知管理器
        stock_manager.schedule_notification(nowuid, projectname)

    except Exception as e:
        logging.error(f"❌ 上架商品失败：{projectname} - {e}")




    
    
def erjifenleibiao(uid, nowuid, projectname, row):
    ejfl.insert_one({
        'uid': uid,
        'nowuid': nowuid,
        'projectname': projectname,
        'row': row,
        'text': f'''
<b>✅您的账户已打包完成，请查收！</b>

<b>🔐二级密码:请在json文件中【two2fa】查看！</b>

<b>⚠️注意：请马上检查账户，1小时内出现问题，联系客服处理！</b>
<b>‼️超过售后时间，损失自付，无需多言！</b>

<b>🔹 9号客服  @o9eth   @o7eth</b>
<b>🔹 频道  @idclub9999</b>
<b>🔹补货通知  @p5540</b>
        ''',
        'money': 0
    })


def fenleibiao(uid, projectname,row):
    fenlei.insert_one({
        'uid': uid,
        'projectname': projectname,
        'row': row
    })

def user_logging(uid, projectname , user_id, today_money, today_time):
    log_data = {
        'uid': uid,
        'projectname': projectname,
        'user_id': user_id,
        'today_money': today_money,
        'today_time': today_time,
        'log_time': datetime.now()
    }
    try:
        user_log.insert_one(log_data)
        print(f"✅ 日志已记录: {log_data}")
        logging.info(f"日志已记录: {log_data}")
    except Exception as e:
        error_msg = f"❌ 日志记录失败: {e}"
        print(error_msg)
        logging.error(error_msg)

def sydata(tranhash):
    """使用数据插入函数"""
    try:
        shiyong.insert_one({'tranhash': tranhash})
        logging.info(f"✅ 插入使用数据：{tranhash}")
    except Exception as e:
        logging.error(f"❌ 插入使用数据失败：{tranhash} - {e}")

def kehuduanurl(api, key):
    """客户端URL插入函数"""
    try:
        get_kehuduan.insert_one({
            'api': api,
            'key': key,
            'tcid': 0,
        })
        logging.info(f"✅ 插入客户端URL：{api}")
    except Exception as e:
        logging.error(f"❌ 插入客户端URL失败：{api} - {e}")

# ✅ 新增：实用工具函数
def get_product_stock(nowuid: str) -> int:
    """获取商品库存数量"""
    try:
        return hb.count_documents({'nowuid': nowuid, 'state': 0})
    except Exception as e:
        logging.error(f"❌ 获取库存失败：nowuid={nowuid} - {e}")
        return 0

def get_user_info(user_id: int) -> dict:
    """获取用户信息"""
    try:
        return user.find_one({'user_id': user_id}) or {}
    except Exception as e:
        logging.error(f"❌ 获取用户信息失败：user_id={user_id} - {e}")
        return {}

def update_user_balance(user_id: int, amount: float, balance_type: str = 'USDT') -> bool:
    """更新用户余额"""
    try:
        result = user.update_one(
            {'user_id': user_id},
            {'$inc': {balance_type: amount}}
        )
        if result.modified_count > 0:
            logging.info(f"✅ 更新用户余额：user_id={user_id}, {balance_type}+={amount}")
            return True
        else:
            logging.warning(f"⚠️ 用户余额更新无变化：user_id={user_id}")
            return False
    except Exception as e:
        logging.error(f"❌ 更新用户余额失败：user_id={user_id} - {e}")
        return False
    
    
def keybutton(Row, first):
    """按钮模板插入函数"""
    try:
        get_key.insert_one({
            'Row': Row,
            'first': first,
            'projectname': '点击修改内容',
            'text': '',
            'file_id': '',
            'file_type': '',
            'key_text': '',
            'keyboard': b'\x80\x03]q\x00.',
            'entities': b'\x80\x03]q\x00.'
        })
        logging.info(f"✅ 插入按钮模板 Row={Row}, first={first}")
    except Exception as e:
        logging.error(f"❌ 插入按钮模板失败：{e}")
    
    
def user_data(key_id, user_id, username, fullname, lastname, state, creation_time, last_contact_time):
    try:
        user.insert_one({
            'count_id': key_id,
            'user_id': user_id,
            'username': username,
            'fullname': fullname,
            'lastname': lastname,
            'state': state,
            'creation_time': creation_time,
            'last_contact_time': last_contact_time,
            'USDT': 0,
            'zgje': 0,
            'zgsl': 0,
            'sign': 0,
            'lang': 'zh',
            'verified': False   # ✅ 添加这一行
        })
        logging.info(f"✅ 新增用户：{user_id} ({username})")
    except Exception as e:
        logging.error(f"❌ 用户写入失败：{user_id} - {e}")

if shangtext.find_one({}) is None:
    logging.info("🔧 初始化 shangtext 数据")
    fstext = '''
 💎本店业务💎 

飞机号，协议号,  直登号(tdata) 批发/零售 !
开通飞机会员,  能量租用&TRX兑换 , 老号老群老频道 !

❗️ 未使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！

❗️ 免责声明：本店所有商品，仅用于娱乐测试，不得用于违法活动！ 请遵守当地法律法规！

⚙️ /start   ⬅️点击命令打开底部菜单!
    '''.strip()
    shang_text('欢迎语', fstext)
    shang_text('欢迎语样式', b'\x80\x03]q\x00.')
    shang_text('充值地址', '')
    shang_text('营业状态', 1)
    logging.info("✅ shangtext 初始化完成")
# ================================ 多机器人分销系统数据表 ================================

# 代理机器人信息表
agent_bots = db_manager.bot_db["agent_bots"]

# 代理商品价格表
agent_product_prices = db_manager.bot_db["agent_product_prices"]

# 代理订单记录表
agent_orders = db_manager.bot_db["agent_orders"]

# 代理提现申请表
agent_withdrawals = db_manager.bot_db["agent_withdrawals"]

# 提现申请表（总部系统）
withdrawal_requests = db_manager.bot_db["withdrawal_requests"]

# ================================ 多机器人分销系统数据操作函数 ================================

def create_agent_bot_data(agent_bot_id, agent_name, agent_token, agent_username, owner_id, commission_rate, creation_time):
    """创建代理机器人信息"""
    try:
        agent_bots.insert_one({
            'agent_bot_id': agent_bot_id,           # 代理机器人唯一ID
            'agent_name': agent_name,               # 代理名称
            'agent_token': agent_token,             # 代理机器人Token
            'agent_username': agent_username,       # 代理机器人用户名 @xxx
            'owner_id': owner_id,                   # 总部管理员ID
            'commission_rate': commission_rate,     # 佣金比例%
            'status': 'active',                     # 状态: active/inactive/suspended
            'creation_time': creation_time,         # 创建时间
            'last_sync_time': '',                   # 最后同步时间
            'total_users': 0,                       # 代理机器人用户总数
            'total_sales': 0.0,                     # 总销售额
            'total_commission': 0.0,                # 总佣金
            'available_balance': 0.0,               # 可提现余额
            'withdrawn_amount': 0.0,                # 已提现金额
            'settings': {
                'welcome_message': '',              # 自定义欢迎语
                'customer_service': '',             # 客服联系方式
                'auto_delivery': True,              # 自动发货
                'allow_recharge': True,             # 允许充值
                'min_purchase': 0.0,                # 最小购买金额
            }
        })
        logging.info(f"✅ 创建代理机器人成功：{agent_name} (@{agent_username})")
        return True
    except Exception as e:
        logging.error(f"❌ 创建代理机器人失败：{agent_name} - {e}")
        return False

def create_agent_product_price_data(agent_bot_id, original_nowuid, agent_price, is_active):
    """创建代理商品价格"""
    try:
        agent_product_prices.insert_one({
            'agent_bot_id': agent_bot_id,           # 代理机器人ID
            'original_nowuid': original_nowuid,     # 总部商品nowuid
            'agent_price': agent_price,             # 代理设置的价格
            'is_active': is_active,                 # 是否启用销售
            'sales_count': 0,                       # 销售数量
            'total_revenue': 0.0,                   # 总收入
            'last_sale_time': '',                   # 最后销售时间
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        logging.info(f"✅ 创建代理商品价格：agent_bot_id={agent_bot_id}, nowuid={original_nowuid}")
        return True
    except Exception as e:
        logging.error(f"❌ 创建代理商品价格失败：{e}")
        return False

def create_agent_order_data(order_id, agent_bot_id, customer_id, original_nowuid, quantity, 
                           agent_price, cost_price, profit, commission, order_time):
    """创建代理订单记录"""
    try:
        agent_orders.insert_one({
            'order_id': order_id,                   # 订单ID
            'agent_bot_id': agent_bot_id,           # 代理机器人ID
            'customer_id': customer_id,             # 客户ID（在代理机器人中的ID）
            'original_nowuid': original_nowuid,     # 原始商品nowuid
            'quantity': quantity,                   # 购买数量
            'agent_price': agent_price,             # 代理售价
            'cost_price': cost_price,               # 成本价
            'profit': profit,                       # 利润
            'commission': commission,               # 代理佣金
            'status': 'completed',                  # 订单状态
            'order_time': order_time,               # 订单时间
            'delivery_content': '',                 # 发货内容
        })
        logging.info(f"✅ 创建代理订单：order_id={order_id}, agent_bot_id={agent_bot_id}")
        return True
    except Exception as e:
        logging.error(f"❌ 创建代理订单失败：{e}")
        return False

def create_agent_withdrawal_data(withdrawal_id, agent_bot_id, amount, payment_method, 
                                payment_account, status, apply_time):
    """创建代理提现申请"""
    try:
        agent_withdrawals.insert_one({
            'withdrawal_id': withdrawal_id,         # 提现ID
            'agent_bot_id': agent_bot_id,           # 代理机器人ID
            'amount': amount,                       # 提现金额
            'payment_method': payment_method,       # 提现方式
            'payment_account': payment_account,     # 收款账户
            'status': status,                       # pending/approved/rejected/completed
            'apply_time': apply_time,               # 申请时间
            'process_time': '',                     # 处理时间
            'process_by': '',                       # 处理人
            'notes': '',                            # 备注
        })
        logging.info(f"✅ 创建提现申请：withdrawal_id={withdrawal_id}, agent_bot_id={agent_bot_id}")
        return True
    except Exception as e:
        logging.error(f"❌ 创建提现申请失败：{e}")
        return False

# ================================ 代理机器人独立用户系统函数 ================================

def normalize_agent_bot_id(agent_bot_id):
    """
    规范化agent_bot_id，确保始终保留"agent_"前缀
    例如: 
    - "62448807124351dfe5cc48d4" -> "agent_62448807124351dfe5cc48d4"
    - "agent_62448807124351dfe5cc48d4" -> "agent_62448807124351dfe5cc48d4"
    """
    if not agent_bot_id:
        return agent_bot_id
    agent_bot_id = str(agent_bot_id).strip()
    if agent_bot_id.startswith('agent_'):
        return agent_bot_id
    return f"agent_{agent_bot_id}"

def _get_agent_id_suffix(agent_bot_id):
    """
    从完整的agent_bot_id中提取ID后缀
    例如: agent_62448807124351dfe5cc48d4 -> 62448807124351dfe5cc48d4
    如果没有agent_前缀，直接返回原值
    """
    if agent_bot_id.startswith('agent_'):
        return agent_bot_id[6:]  # 去掉 'agent_' 前缀
    return agent_bot_id

def agent_users_collection_name(agent_bot_id):
    """
    获取代理用户集合的标准名称
    统一格式: agent_users_{id_without_prefix}
    """
    id_suffix = _get_agent_id_suffix(agent_bot_id)
    return f"agent_users_{id_suffix}"

def get_agent_bot_user_collection(agent_bot_id):
    """获取代理机器人的独立用户集合"""
    agent_bot_id = normalize_agent_bot_id(agent_bot_id)
    id_suffix = _get_agent_id_suffix(agent_bot_id)
    collection_name = f"agent_users_{id_suffix}"
    logging.info(f"🔍 获取用户集合: agent_bot_id={agent_bot_id}, collection={collection_name}")
    return db_manager.bot_db[collection_name]

def get_agent_bot_topup_collection(agent_bot_id):
    """获取代理机器人的独立充值记录集合"""
    id_suffix = _get_agent_id_suffix(agent_bot_id)
    collection_name = f"agent_topup_{id_suffix}"
    return db_manager.bot_db[collection_name]

def get_agent_bot_gmjlu_collection(agent_bot_id):
    """获取代理机器人的独立购买记录集合"""
    id_suffix = _get_agent_id_suffix(agent_bot_id)
    collection_name = f"agent_gmjlu_{id_suffix}"
    return db_manager.bot_db[collection_name]

def create_agent_user_data(agent_bot_id, user_id, username, fullname, creation_time):
    """在代理机器人中创建独立用户"""
    try:
        agent_bot_id = normalize_agent_bot_id(agent_bot_id)
        agent_users = get_agent_bot_user_collection(agent_bot_id)
        
        # 获取该代理机器人的最大count_id
        last_user = agent_users.find_one(sort=[('count_id', -1)])
        count_id = (last_user['count_id'] if last_user else 0) + 1
        
        agent_users.insert_one({
            'count_id': count_id,                   # 代理内部用户编号
            'user_id': user_id,                     # Telegram用户ID
            'username': username,                   # 用户名
            'fullname': fullname,                   # 全名
            'USDT': 0.0,                           # USDT余额（完全独立）
            'state': '1',                          # 状态
            'lang': 'zh',                          # 语言
            'creation_time': creation_time,         # 创建时间
            'zgje': 0.0,                           # 总购金额
            'zgsl': 0,                             # 总购数量
            'sign': 0,                             # 签到
            'last_contact_time': creation_time,     # 最后联系时间
            'verified': False,                     # 是否验证
        })
        
        logging.info(f"✅ 代理机器人创建用户：agent_bot_id={agent_bot_id}, user_id={user_id}")
        return True, count_id
    except Exception as e:
        logging.error(f"❌ 代理机器人创建用户失败：{e}")
        return False, 0

def get_agent_bot_user(agent_bot_id, user_id):
    """获取代理机器人用户信息"""
    try:
        agent_bot_id = normalize_agent_bot_id(agent_bot_id)
        agent_users = get_agent_bot_user_collection(agent_bot_id)
        return agent_users.find_one({'user_id': user_id})
    except Exception as e:
        logging.error(f"❌ 获取代理用户失败：{e}")
        return None

def ensure_agent_user_exists(agent_bot_id, user_id, username=None, fullname=None):
    """
    确保代理用户存在，如果不存在则自动创建
    这是一个兜底函数，用于防止用户不存在导致的错误
    """
    try:
        agent_bot_id = normalize_agent_bot_id(agent_bot_id)
        agent_user = get_agent_bot_user(agent_bot_id, user_id)
        
        if agent_user:
            return True, agent_user
        
        # 用户不存在，创建新用户
        creation_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        success, count_id = create_agent_user_data(
            agent_bot_id=agent_bot_id,
            user_id=user_id,
            username=username or 'unknown',
            fullname=fullname or 'Unknown User',
            creation_time=creation_time
        )
        
        if success:
            agent_user = get_agent_bot_user(agent_bot_id, user_id)
            logging.info(f"✅ 自动创建代理用户：agent_bot_id={agent_bot_id}, user_id={user_id}")
            return True, agent_user
        else:
            logging.error(f"❌ 自动创建代理用户失败：agent_bot_id={agent_bot_id}, user_id={user_id}")
            return False, None
            
    except Exception as e:
        logging.error(f"❌ 确保代理用户存在失败：{e}")
        return False, None

def update_agent_bot_user_balance(agent_bot_id, user_id, amount, balance_type='USDT'):
    """更新代理机器人用户余额（独立系统）"""
    try:
        agent_bot_id = normalize_agent_bot_id(agent_bot_id)
        
        # 确保用户存在
        exists, agent_user = ensure_agent_user_exists(agent_bot_id, user_id)
        if not exists or not agent_user:
            logging.error(f"❌ 用户不存在且创建失败：agent_bot_id={agent_bot_id}, user_id={user_id}")
            return False
        
        agent_users = get_agent_bot_user_collection(agent_bot_id)
        result = agent_users.update_one(
            {'user_id': user_id},
            {'$inc': {balance_type: amount}}
        )
        if result.modified_count > 0:
            logging.info(f"✅ 更新代理用户余额：agent_bot_id={agent_bot_id}, user_id={user_id}, {balance_type}+={amount}")
            return True
        return False
    except Exception as e:
        logging.error(f"❌ 更新代理用户余额失败：{e}")
        return False

# ================================ 工具函数 ================================

def get_agent_bot_info(agent_bot_id):
    """获取代理机器人信息"""
    try:
        return agent_bots.find_one({'agent_bot_id': agent_bot_id})
    except Exception as e:
        logging.error(f"❌ 获取代理机器人信息失败：{e}")
        return None

def get_agent_product_price(agent_bot_id, original_nowuid):
    """获取代理商品价格"""
    try:
        return agent_product_prices.find_one({
            'agent_bot_id': agent_bot_id,
            'original_nowuid': original_nowuid,
            'is_active': True
        })
    except Exception as e:
        logging.error(f"❌ 获取代理商品价格失败：{e}")
        return None

def get_real_time_stock(original_nowuid):
    """获取实时库存（从总部）"""
    try:
        return hb.count_documents({'nowuid': original_nowuid, 'state': 0})
    except Exception as e:
        logging.error(f"❌ 获取实时库存失败：{e}")
        return 0

def generate_agent_bot_id():
    """生成代理机器人唯一ID"""
    import uuid
    import time
    timestamp = str(int(time.time()))[-8:]
    random_part = str(uuid.uuid4()).replace('-', '')[:16]
    return f"agent_{timestamp}{random_part}"

def get_agent_stats(agent_bot_id, period='all'):
    """获取代理机器人的统计数据（基于 agent_orders 集合，兼容 agent_gmjlu_{id} 回退）
    
    Args:
        agent_bot_id: 代理机器人ID
        period: 时间周期 '7d'|'17d'|'30d'|'90d'|'all'
    
    Returns:
        dict: 统计数据字典，包含销售额、佣金、订单数等信息
        None: 如果发生错误
    """
    try:
        logging.info(f"🔍 get_agent_stats called for agent_bot_id: {agent_bot_id}, period: {period}")
        
        # 获取代理机器人基本信息
        agent_info = agent_bots.find_one({'agent_bot_id': agent_bot_id})
        if not agent_info:
            logging.warning(f"❌ Agent not found: {agent_bot_id}")
            return None
        
        # 提取ID后缀用于集合名称
        id_suffix = _get_agent_id_suffix(agent_bot_id)
        logging.info(f"✅ Found agent: {agent_info.get('agent_name')}, ID suffix: {id_suffix}")
        
        commission_rate = agent_info.get('commission_rate', 0) / 100
        logging.info(f"📊 Commission rate: {commission_rate}")
        
        # 计算时间范围
        start_time = None
        if period != 'all':
            days_map = {'7d': 7, '17d': 17, '30d': 30, '90d': 90}
            days = days_map.get(period, 30)
            start_time = datetime.now() - timedelta(days=days)
            logging.info(f"📅 Time filter: orders since {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # ========== 主统计源：agent_orders 集合 ==========
        total_sales = 0.0
        order_count = 0
        total_commission = 0.0
        data_source = "agent_orders"
        
        orders_sales = 0.0
        orders_count = 0
        orders_commission = 0.0
        
        try:
            # 构建时间过滤管道（兼容 datetime 和 string 格式）
            pipeline = []
            
            # 1. 匹配代理机器人
            match_stage = {'agent_bot_id': agent_bot_id}
            pipeline.append({'$match': match_stage})
            
            # 2. 归一化 order_time 字段为 datetime 类型
            pipeline.append({
                '$addFields': {
                    '_orderTime': {
                        '$cond': {
                            'if': {'$eq': [{'$type': '$order_time'}, 'date']},
                            'then': '$order_time',
                            'else': {
                                '$dateFromString': {
                                    'dateString': '$order_time',
                                    'onError': None,
                                    'onNull': None
                                }
                            }
                        }
                    }
                }
            })
            
            # 3. 时间过滤（如果需要）
            if start_time:
                pipeline.append({
                    '$match': {
                        '_orderTime': {'$gte': start_time}
                    }
                })
            
            # 4. 聚合计算
            pipeline.append({
                '$group': {
                    '_id': None,
                    'total_sales': {
                        '$sum': {
                            '$multiply': [
                                {'$ifNull': ['$agent_price', 0]},
                                {'$ifNull': ['$quantity', 1]}
                            ]
                        }
                    },
                    'total_commission': {
                        '$sum': {
                            '$ifNull': ['$commission', 0]
                        }
                    },
                    'order_count': {'$sum': 1}
                }
            })
            
            result = list(agent_orders.aggregate(pipeline))
            
            if result and result[0]['order_count'] > 0:
                stats = result[0]
                orders_sales = float(stats.get('total_sales', 0))
                orders_count = stats.get('order_count', 0)
                orders_commission = float(stats.get('total_commission', 0))
                
                # 如果 commission 字段缺失，回退计算
                if orders_commission == 0 and orders_sales > 0:
                    orders_commission = orders_sales * commission_rate
                
                logging.info(f"📊 agent_orders data - Sales: {orders_sales:.2f}, Commission: {orders_commission:.2f}, Orders: {orders_count}")
        except Exception as e:
            logging.warning(f"⚠️ Error querying agent_orders: {str(e)}")
            orders_count = 0
        
        # ========== 同时检查 agent_gmjlu 集合 ==========
        gmjlu_sales = 0.0
        gmjlu_count = 0
        gmjlu_commission = 0.0
        
        try:
            agent_gmjlu = get_agent_bot_gmjlu_collection(agent_bot_id)
            
            # 构建时间过滤
            match_filter = {'leixing': 'purchase'}
            if start_time:
                start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
                match_filter['timer'] = {'$gte': start_time_str}
            
            pipeline = [
                {'$match': match_filter},
                {
                    '$group': {
                        '_id': None,
                        'total_sales': {'$sum': '$ts'},
                        'order_count': {'$sum': 1}
                    }
                }
            ]
            
            result = list(agent_gmjlu.aggregate(pipeline))
            
            if result:
                stats = result[0]
                gmjlu_sales = float(stats.get('total_sales', 0))
                gmjlu_count = stats.get('order_count', 0)
                gmjlu_commission = gmjlu_sales * commission_rate
                logging.info(f"📊 agent_gmjlu data - Sales: {gmjlu_sales:.2f}, Commission: {gmjlu_commission:.2f}, Orders: {gmjlu_count}")
        except Exception as e:
            logging.warning(f"⚠️ Error querying agent_gmjlu: {str(e)}")
            gmjlu_count = 0
        
        # ========== 选择数据更多的源 ==========
        if gmjlu_count > orders_count:
            # gmjlu 有更多数据，使用它
            total_sales = gmjlu_sales
            order_count = gmjlu_count
            total_commission = gmjlu_commission
            data_source = f"agent_gmjlu_{id_suffix}"
            logging.info(f"✅ Using gmjlu (has more data: {gmjlu_count} vs {orders_count} orders)")
        elif orders_count > 0:
            # agent_orders 有数据且更多，使用它
            total_sales = orders_sales
            order_count = orders_count
            total_commission = orders_commission
            data_source = "agent_orders"
            logging.info(f"✅ Using agent_orders (has more data: {orders_count} vs {gmjlu_count} orders)")
        else:
            # 两边都没数据
            total_sales = 0.0
            order_count = 0
            total_commission = 0.0
            data_source = "none"
            logging.warning(f"⚠️ No data in either agent_orders or agent_gmjlu")
        
        logging.info(f"📊 Final data source: {data_source} - Sales: {total_sales:.2f}, Commission: {total_commission:.2f}, Orders: {order_count}")
        
        # ========== 计算已提现金额（全部时间，从 agent_withdrawals） ==========
        withdrawal_pipeline = [
            {
                '$match': {
                    'agent_bot_id': agent_bot_id,
                    'status': 'completed'
                }
            },
            {
                '$group': {
                    '_id': None,
                    'total_withdrawn': {'$sum': '$amount'}
                }
            }
        ]
        
        withdrawal_result = list(agent_withdrawals.aggregate(withdrawal_pipeline))
        withdrawn_amount = float(withdrawal_result[0].get('total_withdrawn', 0)) if withdrawal_result else 0.0
        
        # ========== 计算可用余额（全部时间累计佣金 - 已提现金额） ==========
        # 如果当前周期不是"全部"，需要重新计算全部时间的佣金
        if period != 'all':
            # 同时查询 agent_orders 和 agent_gmjlu 的全部时间数据
            all_orders_commission = 0.0
            all_orders_count = 0
            all_gmjlu_commission = 0.0
            all_gmjlu_count = 0
            
            try:
                # 从 agent_orders 获取全部时间数据
                all_time_pipeline = [
                    {'$match': {'agent_bot_id': agent_bot_id}},
                    {
                        '$group': {
                            '_id': None,
                            'total_sales': {
                                '$sum': {
                                    '$multiply': [
                                        {'$ifNull': ['$agent_price', 0]},
                                        {'$ifNull': ['$quantity', 1]}
                                    ]
                                }
                            },
                            'total_commission': {
                                '$sum': {'$ifNull': ['$commission', 0]}
                            },
                            'order_count': {'$sum': 1}
                        }
                    }
                ]
                
                all_result = list(agent_orders.aggregate(all_time_pipeline))
                
                if all_result and all_result[0].get('order_count', 0) > 0:
                    all_orders_count = all_result[0].get('order_count', 0)
                    all_orders_commission = float(all_result[0].get('total_commission', 0))
                    if all_orders_commission == 0:
                        all_total_sales = float(all_result[0].get('total_sales', 0))
                        all_orders_commission = all_total_sales * commission_rate
            except Exception as e:
                logging.warning(f"⚠️ Error getting all-time agent_orders data: {e}")
            
            try:
                # 从 agent_gmjlu 获取全部时间数据
                agent_gmjlu = get_agent_bot_gmjlu_collection(agent_bot_id)
                all_sales_pipeline = [
                    {'$match': {'leixing': 'purchase'}},
                    {
                        '$group': {
                            '_id': None,
                            'total_sales': {'$sum': '$ts'},
                            'order_count': {'$sum': 1}
                        }
                    }
                ]
                all_sales_result = list(agent_gmjlu.aggregate(all_sales_pipeline))
                if all_sales_result and all_sales_result[0].get('order_count', 0) > 0:
                    all_gmjlu_count = all_sales_result[0].get('order_count', 0)
                    all_total_sales = float(all_sales_result[0].get('total_sales', 0))
                    all_gmjlu_commission = all_total_sales * commission_rate
            except Exception as e:
                logging.warning(f"⚠️ Error getting all-time agent_gmjlu data: {e}")
            
            # 使用数据更多的源计算余额
            if all_gmjlu_count > all_orders_count:
                all_total_commission = all_gmjlu_commission
                logging.info(f"💰 All-time commission from gmjlu: {all_total_commission:.2f} ({all_gmjlu_count} orders)")
            else:
                all_total_commission = all_orders_commission
                logging.info(f"💰 All-time commission from agent_orders: {all_total_commission:.2f} ({all_orders_count} orders)")
            
            available_balance = all_total_commission - withdrawn_amount
        else:
            available_balance = total_commission - withdrawn_amount
        
        logging.info(f"💰 Withdrawn: {withdrawn_amount:.2f}, Available balance: {available_balance:.2f}")
        
        # ========== 获取用户数量（全部时间） ==========
        agent_users = get_agent_bot_user_collection(agent_bot_id)
        total_users = agent_users.count_documents({})
        logging.info(f"👥 Total users: {total_users}")
        
        # ========== 获取待处理提现（全部时间） ==========
        pending_withdrawals = list(agent_withdrawals.find({
            'agent_bot_id': agent_bot_id,
            'status': 'pending'
        }))
        pending_withdrawal_count = len(pending_withdrawals)
        pending_withdrawal_amount = sum(w.get('amount', 0) for w in pending_withdrawals)
        
        # ========== 计算平均订单额和利润率 ==========
        avg_order = (total_sales / order_count) if order_count > 0 else 0.0
        profit_rate = (total_commission / total_sales * 100) if total_sales > 0 else agent_info.get('commission_rate', 0)
        
        result_stats = {
            'total_sales': total_sales,
            'total_commission': total_commission,
            'available_balance': available_balance,
            'withdrawn_amount': withdrawn_amount,
            'total_users': total_users,
            'order_count': order_count,
            'pending_withdrawal_count': pending_withdrawal_count,
            'pending_withdrawal_amount': float(pending_withdrawal_amount),
            'avg_order': avg_order,
            'profit_rate': profit_rate,
            'period': period,
            'data_source': data_source  # 用于调试
        }
        
        logging.info(f"✅ get_agent_stats returning: {result_stats}")
        
        return result_stats
        
    except Exception as e:
        logging.error(f"❌ 获取代理统计数据失败：{e}")
        import traceback
        traceback.print_exc()
        # 返回安全的零值对象
        return {
            'total_sales': 0.0,
            'total_commission': 0.0,
            'available_balance': 0.0,
            'withdrawn_amount': 0.0,
            'total_users': 0,
            'order_count': 0,
            'pending_withdrawal_count': 0,
            'pending_withdrawal_amount': 0.0,
            'avg_order': 0.0,
            'profit_rate': 0.0,
            'period': period,
            'data_source': 'error'
        }

# ================================ 初始化多机器人分销系统 ================================

def init_multi_bot_distribution_system():
    """初始化多机器人分销系统"""
    try:
        # 创建索引以提高查询性能
        agent_bots.create_index("agent_bot_id", unique=True)
        agent_bots.create_index("agent_token", unique=True)
        agent_bots.create_index([("status", 1), ("creation_time", -1)])
        
        agent_product_prices.create_index([("agent_bot_id", 1), ("original_nowuid", 1), ("is_active", 1)])
        agent_orders.create_index([("agent_bot_id", 1), ("order_time", -1)])
        agent_withdrawals.create_index([("agent_bot_id", 1), ("status", 1)])
        
        # 总部提现申请表索引
        withdrawal_requests.create_index([("user_id", 1), ("status", 1)])
        withdrawal_requests.create_index([("status", 1), ("created_time", -1)])
        
        logging.info("✅ 多机器人分销系统初始化完成")
        return True
    except Exception as e:
        logging.error(f"❌ 多机器人分销系统初始化失败：{e}")
        return False

# 初始化系统
init_multi_bot_distribution_system()

print("🤖 多机器人分销系统数据表加载完成")
if __name__ == '__main__':
      pass
    