# -*- coding: utf-8 -*-
"""
seed.py — 初始化种子数据：建表 + 种子账号 + 默认提示词/页面内容

用法：python seed.py
首次运行会创建管理员与员工演示账号，并写入默认提示词模板与客人端页面内容。
"""

import auth
import db


def main() -> None:
    db.init_db()

    # —— 种子账号（仅演示用途；生产部署务必修改口令并设置 JWT_SECRET）——
    seeds = [
        ("admin", "系统管理员", "admin", "运营部", "Admin@123"),
        ("staff", "值班员工", "staff", "前台", "Staff@123"),
    ]
    for username, display, role, post, password in seeds:
        if not db.get_user_by_username(username):
            db.create_user(username, display, role, post, auth.hash_password(password))
            print(f"[创建] {username}（{display} / {role}）")
        else:
            print(f"[已存在] {username}")

    # —— 默认提示词与页面内容（幂等：已存在则不覆盖管理员的修改）——
    if db.get_prompt() == db.DEFAULT_PROMPT:
        print("[提示词] 使用默认模板（可在管理后台修改）")
    if db.get_page_content() == db.DEFAULT_HOME_PAGE:
        print("[页面内容] 使用默认欢迎语与 FAQ（可在管理后台修改）")

    print("\n完成。管理员 admin / Admin@123，员工 staff / Staff@123（演示口令，请尽快修改）")


if __name__ == "__main__":
    main()
