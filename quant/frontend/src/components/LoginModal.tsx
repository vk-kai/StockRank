import { useEffect, useRef, useState } from "react";
import {
  cancelPurchaseOrder,
  changeAuthCredentials,
  fetchCaptcha,
  fetchPurchaseOrder,
  fetchPurchaseOrders,
  fetchPurchasePlans,
  loginAuth,
  mockCompletePurchase,
  purchaseAccount,
  quickRegisterAuth,
} from "../api";
import type { AuthSessionData, AuthUser, CaptchaData, PurchaseOrderData, PurchasePlan } from "../api/auth";

export type LoginModalView = "login" | "vip" | "billing";

interface Props {
  authUser: AuthUser | null;
  isGateway?: boolean;
  initialView?: LoginModalView;
  onClose: () => void;
  onLogin: (data: AuthSessionData) => void;
  onRequireLogin?: (reason?: string) => void;
  reason?: string;
}

export default function LoginModal({ authUser, isGateway = false, initialView = "login", onClose, onLogin, onRequireLogin, reason }: Props) {
  const [view, setView] = useState<LoginModalView>(initialView);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newUsername, setNewUsername] = useState(authUser?.username || "");
  const [newPassword, setNewPassword] = useState("");
  const [captchaCode, setCaptchaCode] = useState("");
  const [captcha, setCaptcha] = useState<CaptchaData | null>(null);
  const [showQuickRegisterCaptcha, setShowQuickRegisterCaptcha] = useState(false);
  const [registerCaptchaCode, setRegisterCaptchaCode] = useState("");
  const [registerCaptcha, setRegisterCaptcha] = useState<CaptchaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(reason || "");
  const [plans, setPlans] = useState<PurchasePlan[]>([]);
  const [pendingOrder, setPendingOrder] = useState<PurchaseOrderData | null>(null);
  const [orders, setOrders] = useState<PurchaseOrderData[]>([]);
  const [purchasingKey, setPurchasingKey] = useState("");
  const [payingOrderId, setPayingOrderId] = useState("");
  const payPollTimerRef = useRef<number | null>(null);

  const mustChangeCredentials = !!authUser?.must_change_credentials;
  const closeDisabled = mustChangeCredentials;

  const loadCaptcha = async () => {
    const res = await fetchCaptcha();
    if (res.success && res.data) {
      setCaptcha(res.data);
      setCaptchaCode("");
    }
  };

  const loadRegisterCaptcha = async () => {
    const res = await fetchCaptcha();
    if (res.success && res.data) {
      setRegisterCaptcha(res.data);
      setRegisterCaptchaCode("");
    }
  };

  const loadOrders = async () => {
    if (!authUser) return;
    const res = await fetchPurchaseOrders();
    if (res.success && res.data) {
      setOrders(res.data);
      setPendingOrder(res.data.find((order) => order.status === "pending") || null);
    }
  };

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  useEffect(() => {
    setNewUsername(authUser?.username || "");
  }, [authUser?.username]);

  useEffect(() => {
    loadCaptcha();
    fetchPurchasePlans().then((res) => {
      if (res.success && res.data) setPlans(res.data);
    });
  }, []);

  useEffect(() => {
    if (authUser) loadOrders();
  }, [authUser?.username]);

  useEffect(() => {
    if (reason) setMessage(reason);
  }, [reason]);

  useEffect(() => {
    return () => {
      if (payPollTimerRef.current) window.clearInterval(payPollTimerRef.current);
    };
  }, []);

  const handleLogin = async () => {
    if (!username.trim() || !password || !captchaCode.trim() || !captcha) {
      setMessage("请输入用户名、密码和验证码");
      return;
    }
    setLoading(true);
    try {
      const res = await loginAuth({
        username: username.trim(),
        password,
        captcha_id: captcha.captcha_id,
        captcha_code: captchaCode.trim(),
      });
      if (!res.success || !res.data) {
        setMessage(res.message || "登录失败");
        await loadCaptcha();
        return;
      }
      onLogin(res.data);
      onClose();
    } finally {
      setLoading(false);
    }
  };

  const handleQuickRegister = async () => {
    if (!showQuickRegisterCaptcha) {
      setShowQuickRegisterCaptcha(true);
      setMessage("请输入注册验证码后提交注册。");
      await loadRegisterCaptcha();
      return;
    }
    if (!registerCaptcha || !registerCaptchaCode.trim()) {
      setMessage("请输入注册验证码后再提交");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const res = await quickRegisterAuth({
        captcha_id: registerCaptcha.captcha_id,
        captcha_code: registerCaptchaCode.trim(),
      });
      if (!res.success || !res.data) {
        setMessage(res.message || "一键注册失败，请稍后重试");
        await loadRegisterCaptcha();
        return;
      }
      setUsername(res.data.account.username);
      setPassword(res.data.account.password);
      setShowQuickRegisterCaptcha(false);
      setRegisterCaptcha(null);
      setRegisterCaptchaCode("");
      setView("login");
      setMessage("注册成功，账号和密码已自动填充。请按正常登录流程输入验证码后登录。");
    } finally {
      setLoading(false);
    }
  };

  const handlePurchase = async (plan: PurchasePlan) => {
    if (!authUser) {
      onRequireLogin?.("请先一键注册或登录后再开通 VIP");
      return;
    }
    if (pendingOrder) {
      setMessage("当前账号已有未支付订单，请先支付或取消该订单。");
      return;
    }
    setPurchasingKey(plan.key);
    setMessage("");
    try {
      const res = await purchaseAccount(plan.key);
      if (!res.success || !res.data) {
        if (res.data) setPendingOrder(res.data);
        setMessage(res.message || "创建订单失败，请稍后重试");
        return;
      }
      setPendingOrder(res.data);
      await loadOrders();
    } finally {
      setPurchasingKey("");
    }
  };

  const applyPaidOrder = async (order: PurchaseOrderData) => {
    setPendingOrder(null);
    await loadOrders();
    if (order.user) {
      onLogin({ user: order.user, default_strategy: "MACD_Cross", expires_at: order.user.expires_at });
      setMessage(order.user.must_change_credentials ? "VIP 已开通，请立即修改用户名和密码，否则临时账号失效后将无法继续登录。" : "VIP 已开通。");
    } else {
      setMessage("VIP 已开通。");
    }
  };

  const startPaymentPolling = (orderId: string) => {
    if (payPollTimerRef.current) window.clearInterval(payPollTimerRef.current);
    let attempts = 0;
    payPollTimerRef.current = window.setInterval(async () => {
      attempts += 1;
      const res = await fetchPurchaseOrder(orderId);
      if (res.success && res.data?.status === "paid") {
        if (payPollTimerRef.current) window.clearInterval(payPollTimerRef.current);
        payPollTimerRef.current = null;
        setPayingOrderId("");
        await applyPaidOrder(res.data);
        return;
      }
      if (attempts >= 60) {
        if (payPollTimerRef.current) window.clearInterval(payPollTimerRef.current);
        payPollTimerRef.current = null;
        setPayingOrderId("");
      }
    }, 3000);
  };

  const handlePay = async () => {
    if (!pendingOrder) return;
    const payWindow = window.open("about:blank", "_blank");
    if (payWindow) payWindow.opener = null;
    setPayingOrderId(pendingOrder.order_id);
    setMessage("");
    try {
      let payUrl = pendingOrder.pay_url || "";
      if (!payUrl) {
        const res = await fetchPurchaseOrder(pendingOrder.order_id);
        if (res.success && res.data) {
          setPendingOrder(res.data);
          payUrl = res.data.pay_url || "";
        } else {
          setMessage(res.message || "支付链接未生成，请稍后重试");
        }
      }
      if (!payUrl) {
        payWindow?.close();
        setMessage("支付链接未生成，请检查订单或稍后重试");
        return;
      }
      if (payWindow) {
        payWindow.location.href = payUrl;
      } else {
        window.location.href = payUrl;
      }
      setMessage("已打开支付页面，正在自动检查支付结果。");
      startPaymentPolling(pendingOrder.order_id);
    } finally {
      if (!payPollTimerRef.current) setPayingOrderId("");
    }
  };

  const handleMockPay = async () => {
    if (!pendingOrder) return;
    setPayingOrderId(pendingOrder.order_id);
    setMessage("");
    try {
      const res = await mockCompletePurchase(pendingOrder.order_id);
      if (!res.success || !res.data?.user) {
        setMessage(res.message || "支付确认失败，请稍后重试");
        return;
      }
      await applyPaidOrder({ ...pendingOrder, status: "paid", user: res.data.user });
    } finally {
      setPayingOrderId("");
    }
  };

  const handleCheckPay = async () => {
    if (!pendingOrder) return;
    setPayingOrderId(pendingOrder.order_id);
    setMessage("");
    try {
      const res = await fetchPurchaseOrder(pendingOrder.order_id);
      if (!res.success || !res.data) {
        setMessage(res.message || "查询订单失败，请稍后重试");
        return;
      }
      if (res.data.status === "paid") {
        await applyPaidOrder(res.data);
        return;
      }
      setPendingOrder(res.data);
      setMessage("订单还未支付成功，请完成支付宝付款后再检查");
    } finally {
      setPayingOrderId("");
    }
  };

  const handleCancelOrder = async () => {
    if (!pendingOrder) return;
    setPayingOrderId(pendingOrder.order_id);
    setMessage("");
    try {
      const res = await cancelPurchaseOrder(pendingOrder.order_id);
      if (!res.success) {
        setMessage(res.message || "取消订单失败");
        return;
      }
      setPendingOrder(null);
      await loadOrders();
    } finally {
      setPayingOrderId("");
    }
  };

  const handleChangeCredentials = async () => {
    if (!captcha || !newUsername.trim() || !newPassword || !captchaCode.trim()) {
      setMessage("请输入新用户名、新密码和验证码");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const res = await changeAuthCredentials({
        username: newUsername.trim(),
        password: newPassword,
        captcha_id: captcha.captcha_id,
        captcha_code: captchaCode.trim(),
      });
      if (!res.success || !res.data) {
        setMessage(res.message || "修改账号失败");
        await loadCaptcha();
        return;
      }
      onLogin(res.data);
      setMessage("账号已更新，可继续使用 VIP。");
      onClose();
    } finally {
      setLoading(false);
    }
  };

  const renderLogin = () => (
    <>
      {showQuickRegisterCaptcha ? (
        <div className="quick-register-box">
          <CaptchaRow
            label="注册验证码"
            captcha={registerCaptcha}
            captchaCode={registerCaptchaCode}
            setCaptchaCode={setRegisterCaptchaCode}
            loadCaptcha={loadRegisterCaptcha}
          />
        </div>
      ) : (
        <div className="login-form">
          <label className="login-field">
            <span>用户名</span>
            <input className="pretty-input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </label>
          <label className="login-field">
            <span>密码</span>
            <input
              className="pretty-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleLogin();
              }}
            />
          </label>
          <CaptchaRow captcha={captcha} captchaCode={captchaCode} setCaptchaCode={setCaptchaCode} loadCaptcha={loadCaptcha} />
        </div>
      )}
      <div className={`login-actions ${showQuickRegisterCaptcha ? "register-mode" : ""}`}>
        <button className="modal-close-btn" onClick={handleQuickRegister} disabled={loading} type="button">
          {showQuickRegisterCaptcha ? "提交注册" : "一键注册"}
        </button>
        {!showQuickRegisterCaptcha && (
          <button className="setting-primary-btn" onClick={handleLogin} disabled={loading} type="button">
            <span className="btn-text">{loading ? "处理中..." : "登录"}</span>
          </button>
        )}
      </div>
    </>
  );

  const renderVip = () => (
    <div className="purchase-panel">
      <div className="purchase-title">开通 VIP</div>
      <div className="purchase-desc">VIP 绑定当前登录账号，支付成功后延长账号有效期，并要求设置正式用户名和密码。</div>
      <div className="vip-feature-grid">
        <span>解锁登录专属策略</span>
        <span>保存个人扫描与账单</span>
        <span>到期前可续期叠加</span>
      </div>
      <div className="purchase-plans">
        {plans.map((plan) => (
          <button
            key={plan.key}
            type="button"
            className="purchase-plan-btn"
            onClick={() => handlePurchase(plan)}
            disabled={!!purchasingKey || (!!authUser && (!!pendingOrder || mustChangeCredentials))}
          >
            <span>{plan.label}</span>
            <strong>{plan.price}</strong>
            <small>{plan.duration_days} 天</small>
            <em>{authUser ? "立即支付" : "登录后支付"}</em>
          </button>
        ))}
      </div>
      {!authUser && <div className="purchase-desc">选择套餐后会打开登录窗口，可一键注册临时账号，输入验证码登录后再支付。</div>}
      {authUser && pendingOrder && (
        <div className="purchase-order-box">
          <div>
            待支付订单 <strong>{pendingOrder.order_id}</strong>
            {pendingOrder.plan ? `，${pendingOrder.plan.label} ${pendingOrder.plan.price}` : ""}
          </div>
          <div className="purchase-order-note">
            继续支付这笔订单，或取消后重新选择套餐。
          </div>
          <div className="purchase-order-actions">
            <button type="button" className="purchase-pay-btn purchase-check-btn" onClick={handleCancelOrder} disabled={!!payingOrderId}>
              取消订单
            </button>
            {!pendingOrder.mock && (
              <button type="button" className="purchase-pay-btn purchase-check-btn" onClick={handleCheckPay} disabled={!!payingOrderId}>
                {payingOrderId ? "查询中..." : "检查支付结果"}
              </button>
            )}
            <button
              type="button"
              className="purchase-pay-btn"
              onClick={pendingOrder.mock ? handleMockPay : handlePay}
              disabled={!!payingOrderId}
            >
              {payingOrderId ? "确认中..." : "确认并支付"}
            </button>
          </div>
        </div>
      )}
      {authUser && mustChangeCredentials && renderChangeCredentials()}
    </div>
  );

  const renderChangeCredentials = () => (
    <div className="purchase-account-box">
      <div className="purchase-title">修改用户名和密码</div>
      <div className="purchase-warning critical">VIP 已开通，请完成账号修改后继续使用。不修改用户名和密码，临时账号失效后将无法再次登录。</div>
      <label className="login-field">
        <span>新用户名</span>
        <input className="pretty-input" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
      </label>
      <label className="login-field">
        <span>新密码</span>
        <input className="pretty-input" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
      </label>
      <CaptchaRow captcha={captcha} captchaCode={captchaCode} setCaptchaCode={setCaptchaCode} loadCaptcha={loadCaptcha} />
      <button type="button" className="purchase-pay-btn" onClick={handleChangeCredentials} disabled={loading}>
        {loading ? "提交中..." : "保存账号"}
      </button>
    </div>
  );

  const renderBilling = () => (
    <div className="purchase-panel">
      <div className="purchase-title">账单</div>
      {orders.length === 0 ? (
        <div className="purchase-desc">暂无订单。</div>
      ) : (
        <div className="billing-list">
          {orders.map((order) => (
            <div className="billing-row" key={order.order_id}>
              <div>
                <strong>{order.plan?.label || "VIP"}</strong>
                <span>{order.order_id}</span>
                <span>生成：{formatOrderTime(order.created_at)}</span>
              </div>
              <div>
                <span>{order.plan ? `¥${Number(order.plan.price).toFixed(2)}` : "--"}</span>
                <em className={`billing-status ${order.status}`}>{order.status === "paid" ? "已支付" : order.status === "cancelled" ? "已取消" : "待支付"}</em>
                <span>支付：{formatOrderTime(order.paid_at)}</span>
                <span>到期：{formatOrderTime(order.expires_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderGatewayRedirect = (target: "login" | "vip") => (
    <div className="purchase-panel">
      <div className="purchase-title">{target === "vip" ? "VIP 已并入 StockRank" : "统一登录"}</div>
      <div className="purchase-desc">
        {target === "vip"
          ? "量化区已并入 StockRank 统一门禁，登录/注册/VIP 购买入口已下线；请在主站登录后直接使用全部策略。"
          : "量化区已并入 StockRank 统一门禁，请前往主站登录；登录后即可直接访问本系统。"}
      </div>
      <button type="button" className="setting-primary-btn" onClick={() => { window.location.href = "/"; }}>
        <span className="btn-text">前往 StockRank 登录</span>
      </button>
    </div>
  );

  return (
    <div className="modal-backdrop login-modal-backdrop" onClick={closeDisabled ? undefined : onClose}>
      <div className="login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header login-modal-header">
          <h3>{view === "vip" ? "开通 VIP" : view === "billing" ? "账单" : "登录"}</h3>
          <button className="modal-close-btn" onClick={onClose} disabled={closeDisabled}>关闭</button>
        </div>

        {message && <div className="login-message">{message}</div>}

        {view === "login" && (isGateway ? renderGatewayRedirect("login") : renderLogin())}
        {view === "vip" && (isGateway ? renderGatewayRedirect("vip") : renderVip())}
        {view === "billing" && renderBilling()}
      </div>
    </div>
  );
}

function formatOrderTime(value?: string) {
  if (!value) return "--";
  return value;
}

function CaptchaRow({
  label = "动态验证码",
  captcha,
  captchaCode,
  setCaptchaCode,
  loadCaptcha,
}: {
  label?: string;
  captcha: CaptchaData | null;
  captchaCode: string;
  setCaptchaCode: (value: string) => void;
  loadCaptcha: () => void;
}) {
  return (
    <label className="login-field">
      <span>{label}</span>
      <div className="captcha-row">
        <input className="pretty-input" value={captchaCode} onChange={(e) => setCaptchaCode(e.target.value)} />
        <button
          type="button"
          className="captcha-image-btn"
          onClick={loadCaptcha}
          dangerouslySetInnerHTML={{ __html: captcha?.image_svg || "" }}
          aria-label="刷新验证码"
        />
      </div>
    </label>
  );
}
