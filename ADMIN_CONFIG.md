# Admin Permission Configuration

## Overview

This bot now uses environment-based admin permission checks via the `ADMIN_IDS` configuration in `.env`. All admin permissions are centralized and no longer depend on database `state` fields.

## Configuration

### Environment Variables

Add the following to your `.env` file:

```bash
# Admin Configuration - Comma-separated list of admin user IDs
ADMIN_IDS=123456789,987654321
```

**Important:**
- User IDs must be **numeric Telegram user IDs**
- Separate multiple IDs with **commas** (no spaces)
- Changes require **bot restart** to take effect

## Admin Functions

All admin-related features now check the `ADMIN_IDS` list:

### 1. Admin Panel (`/admin`)
- Opens the admin control panel
- Shows platform statistics
- Access to all admin tools

### 2. Admin Commands
- `/add <user_id> <+/-amount>` - Adjust user balance
- `/cha <user_id>` - Check user information
- `/gg <message>` - Broadcast message to all users
- `/admin_add @username` or `/admin_add <user_id>` - Add admin (runtime only, requires .env update)
- `/admin_remove @username` or `/admin_remove <user_id>` - Remove admin (runtime only)

### 3. Admin Panel Features
- 用户列表 (User List)
- 用户私发 (Private Message)
- 设置充值地址 (Recharge Address)
- 商品管理 (Product Management)
- 修改欢迎语 (Welcome Message)
- 设置菜单按钮 (Menu Buttons)
- 收入统计 (Income Statistics)
- 导出用户列表 (Export User List)
- 导出下单记录 (Export Orders)
- 销售统计 (Sales Dashboard)
- 库存预警 (Stock Alerts)
- 数据导出 (Data Export)
- 多语言管理 (Multi-language)

### 4. Agent Bot Management (代理机器人管理)
- Create agent bots
- Manage agent bots
- Agent user management
- Agent balance management
- Withdrawal management

### 5. Business Controls
- 开始营业 / 停止营业 (Open/Close business)
- Admins can access even when business is closed

## Implementation Details

### Core Functions

```python
def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

def get_admin_ids() -> list:
    """Get list of admin IDs"""
    return ADMIN_IDS.copy()
```

### MultiBotDistributionSystem

The `is_master_admin()` method now uses env-based admin checks:

```python
def is_master_admin(self, user_id):
    """Check if user is master admin"""
    return is_admin(user_id)
```

### Logging

Admin access is logged at critical entry points:

```python
logging.info(f"Admin panel accessed by user_id={user_id}")
logging.info(f"Agent bot management accessed by user_id={user_id}")
```

## Migration from Database State

### Before (Database-based)
```python
uinfo = user.find_one({'user_id': user_id})
if not uinfo or str(uinfo.get('state')) != '4':
    return  # No permission
```

### After (Environment-based)
```python
if not is_admin(user_id):
    return  # No permission
```

## Testing

### Verify Admin Access

1. **Configure Admin IDs**
   ```bash
   # In .env file
   ADMIN_IDS=YOUR_USER_ID
   ```

2. **Restart Bot**
   ```bash
   # Stop and restart the bot process
   ```

3. **Test Admin Panel**
   - Send `/admin` to the bot
   - Should see admin control panel
   - All buttons should work without permission errors

4. **Test Agent Management**
   - Click "🤖 代理管理" in admin panel
   - Should see agent bot management interface
   - Should not see "您没有权限访问代理机器人管理"

5. **Test Admin Commands**
   - `/add 123456789 +100` - Should work
   - `/cha 123456789` - Should work
   - `/gg Test message` - Should work

### Verify Non-Admin Blocked

1. **Use Non-Admin Account**
   - User ID not in `ADMIN_IDS`

2. **Test Commands**
   - `/admin` - Should show "无权限访问管理员面板"
   - Admin commands should not work

## Security Notes

1. **Never commit `.env` file** - Keep admin IDs private
2. **Use numeric user IDs only** - More secure than usernames
3. **Audit admin list regularly** - Remove inactive admins
4. **Monitor admin actions** - Check logs for suspicious activity

## Troubleshooting

### Admin Access Denied

**Problem:** Admin commands don't work even with correct `ADMIN_IDS`

**Solutions:**
1. Check `.env` file format - no spaces in ADMIN_IDS
2. Verify user ID is correct (numeric)
3. Restart bot after changing `.env`
4. Check logs for permission check results

### Agent Management Not Accessible

**Problem:** "您没有权限访问代理机器人管理"

**Solutions:**
1. Verify `ADMIN_IDS` is set correctly
2. Check `is_master_admin()` is using `is_admin()`
3. Restart bot
4. Check logs: `grep "Agent bot management" bot.log`

## Best Practices

1. **Keep minimal admin list** - Only trusted users
2. **Use separate admin for testing** - Don't use production admin
3. **Document admin changes** - Keep track of who has access
4. **Regular security audits** - Review admin activity
5. **Backup configuration** - Keep `.env` backed up securely

## Files Modified

- `bot.py` - All admin permission checks updated
  - `MultiBotDistributionSystem.is_master_admin()`
  - Admin command handlers: `admin()`, `adm()`, `cha()`, `fbgg()`
  - Admin panel callbacks: `sales_dashboard()`, `stock_alerts()`, etc.
  - Export functions: `export_users_comprehensive()`, etc.
  - Agent management: `agent_bot_management()`
  - Business status checks
  - Admin notification loops

## Support

For issues or questions about admin configuration:
1. Check logs: `tail -f logs/bot.log`
2. Verify configuration: `grep ADMIN_IDS .env`
3. Test with logging enabled
