import logging
import os
from datetime import datetime
from telegram import Bot

logger = logging.getLogger(__name__)

class AgentBotCore:
    def __init__(self, config):
        self.config = config
        
    def process_purchase(self, user_id, product_nowuid, quantity=1):
        """处理购买"""
        try:
            logger.info(f"🔍 开始处理购买: user_id={user_id}, product_nowuid={product_nowuid}, quantity={quantity}")
            
            # 验证用户
            agent_users = self.config.get_agent_user_collection()
            user_info = agent_users.find_one({'user_id': user_id})
            if not user_info:
                return False, "用户不存在"
            
            # 验证商品和价格
            agent_price_info = self.config.agent_product_prices.find_one({
                'agent_bot_id': self.config.AGENT_BOT_ID,
                'original_nowuid': product_nowuid,
                'is_active': True
            })
            
            if not agent_price_info:
                return False, "商品不存在或已下架"
            
            original_product = self.config.ejfl.find_one({'nowuid': product_nowuid})
            if not original_product:
                return False, "原始商品不存在"
            
            # 检查库存
            available_items = list(self.config.hb.find({
                'nowuid': product_nowuid,
                'state': 0
            }).limit(quantity))
            
            if len(available_items) < quantity:
                return False, "库存不足"
            
            # 计算费用
            agent_price = agent_price_info['agent_price']
            total_cost = agent_price * quantity
            user_balance = user_info.get('USDT', 0)
            
            if user_balance < total_cost:
                return False, "余额不足"
            
            # 扣除余额
            new_balance = user_balance - total_cost
            update_result = agent_users.update_one(
                {'user_id': user_id},
                {
                    '$set': {'USDT': new_balance},
                    '$inc': {'zgje': total_cost, 'zgsl': quantity}
                }
            )
            
            if update_result.modified_count == 0:
                return False, "余额扣除失败"
            
            # 标记商品为已售出
            item_ids = [item['_id'] for item in available_items]
            self.config.hb.update_many(
                {'_id': {'$in': item_ids}},
                {'$set': {'state': 1, 'sale_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}
            )
            
            # 处理商品内容和文件发送
            delivered_items = []
            files_sent_count = 0
            
            logger.info(f"🔍 开始处理 {len(available_items)} 个商品")
            
            for i, item in enumerate(available_items, 1):
                logger.info(f"🔍 处理第 {i} 个商品:")
                logger.info(f"   item_id: {item.get('_id')}")
                logger.info(f"   projectname: {item.get('projectname')}")
                logger.info(f"   nowuid: {item.get('nowuid')}")
                logger.info(f"   leixing: {item.get('leixing')}")
                
                # 商品内容
                item_content = str(item.get('_id', ''))
                delivered_items.append(item_content)
                
                # 发送文件
                logger.info(f"🔔 开始为商品 {i} 发送文件")
                try:
                    file_sent = self.send_item_file_to_user(user_id, item, original_product['projectname'])
                    logger.info(f"🔔 商品 {i} 文件发送结果: {file_sent}")
                    
                    if file_sent:
                        files_sent_count += 1
                        logger.info(f"✅ 商品 {i} 文件发送成功")
                    else:
                        logger.warning(f"⚠️ 商品 {i} 文件发送失败")
                        
                except Exception as file_error:
                    logger.error(f"❌ 商品 {i} 文件发送异常: {file_error}")
            
            # 记录订单到代理数据库
            order_id = f"order_{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id}"
            
            agent_gmjlu = self.config.get_agent_gmjlu_collection()
            order_record = {
                'leixing': 'purchase',
                'bianhao': order_id,
                'user_id': user_id,
                'projectname': original_product['projectname'],
                'text': delivered_items[0] if delivered_items else '',
                'ts': total_cost,
                'timer': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'count': quantity
            }
            
            agent_gmjlu.insert_one(order_record)
            
            logger.info(f"✅ 购买完成: 用户{user_id} 购买 {original_product['projectname']} x{quantity}")
            logger.info(f"📁 文件发送统计: {files_sent_count}/{len(available_items)} 个文件发送成功")
            
            return True, {
                'order_id': order_id,
                'product_name': original_product['projectname'],
                'quantity': quantity,
                'total_cost': total_cost,
                'user_balance': new_balance,
                'delivered_items': delivered_items,
                'files_sent': files_sent_count
            }
            
        except Exception as e:
            logger.error(f"❌ 处理购买失败: {e}")
            import traceback
            traceback.print_exc()
            return False, f"购买处理异常: {str(e)}"

    def send_item_file_to_user(self, user_id, item, product_name):
        """发送单个商品的文件给用户"""
        logger.info(f"🔔 开始发送文件流程: user_id={user_id}, product_name={product_name}")
        logger.info(f"🔍 商品数据: {item}")
        
        try:
            # 直接使用华南代理的token
            bot_token = "8585365683:AAFf2IfDjVsqlpDHrEJKcEvO3jzlxF56JzU"
            logger.info(f"🔍 使用代理机器人token")
            
            # 创建机器人实例
            bot = Bot(token=bot_token)
            
            # 获取商品信息
            item_projectname = item.get('projectname', '')
            item_leixing = item.get('leixing', '')
            item_nowuid = item.get('nowuid', '')
            
            logger.info(f"🔍 商品详细信息:")
            logger.info(f"   projectname: {item_projectname}")
            logger.info(f"   leixing: {item_leixing}")
            logger.info(f"   nowuid: {item_nowuid}")
            
            # 根据商品类型和nowuid确定文件路径
            if item_leixing == '协议号':
                product_dir = f'/www/9haobot/9hao/协议号/{item_nowuid}'
            else:
                # 其他类型的文件可能在不同目录
                product_dir = f'/www/9haobot/9hao/{item_leixing}/{item_nowuid}'
            
            logger.info(f"🔍 计算的文件目录: {product_dir}")
            
            # 检查目录是否存在
            if not os.path.exists(product_dir):
                logger.warning(f"⚠️ 商品目录不存在: {product_dir}")
                return False
            
            # 查找目录中的文件
            try:
                files_in_dir = os.listdir(product_dir)
                logger.info(f"🔍 目录 {product_dir} 中的文件: {files_in_dir}")
                
                if not files_in_dir:
                    logger.warning(f"⚠️ 目录为空: {product_dir}")
                    return False
                
                # 优先查找压缩文件和文本文件
                priority_extensions = ['.zip', '.rar', '.7z', '.txt']
                found_files = []
                
                for ext in priority_extensions:
                    for file in files_in_dir:
                        if file.lower().endswith(ext):
                            found_files.append(os.path.join(product_dir, file))
                
                # 如果没找到优先文件，添加其他所有文件
                if not found_files:
                    for file in files_in_dir:
                        file_path = os.path.join(product_dir, file)
                        if os.path.isfile(file_path):
                            found_files.append(file_path)
                
                logger.info(f"🔍 找到的文件列表: {found_files}")
                
                files_sent = 0
                
                # 发送所有找到的文件
                for file_path in found_files:
                    try:
                        file_size = os.path.getsize(file_path)
                        file_name = os.path.basename(file_path)
                        
                        logger.info(f"📁 准备发送文件: {file_name} (大小: {file_size} bytes)")
                        
                        # 检查文件大小（Telegram限制50MB）
                        if file_size > 50 * 1024 * 1024:
                            logger.warning(f"⚠️ 文件太大，跳过: {file_name} ({file_size} bytes)")
                            continue
                        
                        # 发送文件
                        with open(file_path, 'rb') as file:
                            result = bot.send_document(
                                chat_id=user_id,
                                document=file,
                                caption=f"📁 <b>{product_name}</b>\n\n📦 商品文件: {file_name}\n💼 商品编号: {item_projectname}\n🔔 请妥善保存文件内容",
                                parse_mode='HTML'
                            )
                        
                        logger.info(f"✅ 成功发送文件: {file_name} (message_id: {result.message_id})")
                        files_sent += 1
                        
                    except Exception as send_error:
                        logger.error(f"❌ 发送文件失败 {file_name}: {send_error}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                if files_sent > 0:
                    logger.info(f"✅ 总共发送了 {files_sent} 个文件给用户 {user_id}")
                    return True
                else:
                    logger.warning(f"⚠️ 没有成功发送任何文件")
                    return False
                    
            except Exception as list_error:
                logger.error(f"❌ 读取目录失败: {list_error}")
                return False
            
        except Exception as e:
            logger.error(f"❌ 发送文件处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False