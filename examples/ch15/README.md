# 第15章：跨会话记忆

```bash
python -m examples.ch15.demo
python -m unittest examples.ch15.test_demo
```

从 ecom-service-agent 仓库根目录运行，使用 Python 3.11 或以上。需要标准发行版自带的 `sqlite3` 模块，无第三方依赖。

脚本在系统临时目录创建数据库，启动新的Python进程读取，再验证版本更新、旧候选冲突、到期不召回和按用户删除。退出时临时目录自动清理。

示例中的1000、2000为固定教学时刻。`user_id`必须由可信调用方提供，格式检查不是身份认证；代码没有实现真实账号系统、分布式存储或备份清理，也没有训练或调用模型。
