# 期权交易记录页面 UI 自动化测试

针对客户后台「客户首页 → 交易记录 → 期权」页面的前端显示做自动化校验。

- 环境：SIT（https://admin-sit.yxzq.com）
- 资金账号：77000851
- 技术栈：Python + Playwright

## 为什么要先手动登录一次

该后台使用 CAS 统一认证，登录态保存在服务端会话 cookie 里，无法直接注入一个 token。
所以采用「手动登录一次 → 保存登录态 → 后续自动复用」的方式：只需登录一次，
`auth_state.json` 在有效期内可反复使用，测试脚本会自动加载它，不再需要登录。

## 使用步骤

1. 安装依赖（首次）

   ```powershell
   python -m pip install -r requirements.txt
   python -m playwright install chromium
   ```

2. 保存登录态（首次，或登录态过期后重跑）

   ```powershell
   python save_login.py
   ```

   在弹出的浏览器里完成登录，看到后台「客户主页」界面后，回终端按回车。
   会生成 `auth_state.json`。

3. 运行 UI 校验测试

   ```powershell
   python test_option_trade_records.py
   ```

   校验通过/失败结果会打印在终端，页面截图保存在 `screenshots/` 目录。

## 登录态过期怎么办

如果运行测试时又跳到了统一认证登录页，说明 `auth_state.json` 过期了，
重新执行第 2 步 `python save_login.py` 即可。
