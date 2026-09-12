import { requestJson } from "./base";

export interface AuthUser {
  username: string;
  role?: string;
  expires_at?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string;
  must_change_credentials?: boolean;
}

export interface AuthSessionData {
  user: AuthUser | null;
  default_strategy: string;
  expires_at?: string;
  /** 后端是否运行在统一门禁(gateway)模式:登录/注册/VIP 购买已下线,需跳转 StockRank */
  gateway?: boolean;
}

export interface QuickRegisterData {
  account: {
    username: string;
    password: string;
    expires_at: string;
  };
}

export interface CaptchaData {
  captcha_id: string;
  image_svg: string;
  expires_in: number;
}

export interface PurchasePlan {
  key: string;
  label: string;
  price: number;
  duration_days: number;
}

export interface PurchaseAccount {
  username: string;
  password: string;
  expires_at: string;
}

export interface PurchaseOrderData {
  order_id: string;
  status: string;
  mock?: boolean;
  pay_url?: string;
  plan?: PurchasePlan;
  created_at?: string;
  paid_at?: string;
  expires_at?: string;
  user?: AuthUser;
}

export async function fetchAuthSession(): Promise<{ success: boolean; data: AuthSessionData }> {
  return requestJson("/api/auth/session");
}

export async function fetchCaptcha(): Promise<{ success: boolean; data: CaptchaData }> {
  return requestJson("/api/auth/captcha");
}

export async function loginAuth(params: {
  username: string;
  password: string;
  captcha_id: string;
  captcha_code: string;
}): Promise<{ success: boolean; data?: AuthSessionData; message?: string; status?: number }> {
  return requestJson("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function logoutAuth(): Promise<{ success: boolean; data: AuthSessionData }> {
  return requestJson("/api/auth/logout", { method: "POST" });
}

export async function registerAuth(): Promise<{ success: boolean; message?: string; status?: number }> {
  return requestJson("/api/auth/register", { method: "POST" });
}

export async function quickRegisterAuth(params: {
  captcha_id: string;
  captcha_code: string;
}): Promise<{ success: boolean; data?: QuickRegisterData; message?: string; status?: number }> {
  return requestJson("/api/auth/quick-register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function changeAuthCredentials(params: {
  username: string;
  password: string;
  captcha_id: string;
  captcha_code: string;
}): Promise<{ success: boolean; data?: AuthSessionData; message?: string; status?: number }> {
  return requestJson("/api/auth/change-credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function fetchPurchasePlans(): Promise<{ success: boolean; data: PurchasePlan[]; message?: string }> {
  return requestJson("/api/auth/purchase/plans");
}

export async function purchaseAccount(planKey: string): Promise<{ success: boolean; data?: PurchaseOrderData; message?: string; status?: number }> {
  return requestJson("/api/auth/purchase", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_key: planKey }),
  });
}

export async function mockCompletePurchase(orderId: string): Promise<{ success: boolean; data?: { user?: AuthUser; order?: PurchaseOrderData }; message?: string; status?: number }> {
  return requestJson(`/api/auth/purchase/${encodeURIComponent(orderId)}/mock-complete`, { method: "POST" });
}

export async function fetchPurchaseOrder(orderId: string): Promise<{ success: boolean; data?: PurchaseOrderData; message?: string; status?: number }> {
  return requestJson(`/api/auth/purchase/${encodeURIComponent(orderId)}`);
}

export async function fetchPurchaseOrders(): Promise<{ success: boolean; data?: PurchaseOrderData[]; message?: string; status?: number }> {
  return requestJson("/api/auth/purchase");
}

export async function cancelPurchaseOrder(orderId: string): Promise<{ success: boolean; message?: string; status?: number }> {
  return requestJson(`/api/auth/purchase/${encodeURIComponent(orderId)}/cancel`, { method: "POST" });
}

export async function fetchAdminUsers(): Promise<{ success: boolean; data?: AuthUser[]; message?: string; status?: number }> {
  return requestJson("/api/auth/admin/users");
}

export async function createAdminUser(params: {
  username: string;
  password: string;
  expires_at?: string | null;
}): Promise<{ success: boolean; data?: AuthUser; message?: string; status?: number }> {
  return requestJson("/api/auth/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function updateAdminUser(
  username: string,
  params: { username?: string; password?: string; expires_at?: string | null; banned: boolean }
): Promise<{ success: boolean; data?: AuthUser; message?: string; status?: number }> {
  return requestJson(`/api/auth/admin/users/${encodeURIComponent(username)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function deleteAdminUser(username: string): Promise<{ success: boolean; data?: { username: string }; message?: string; status?: number }> {
  return requestJson(`/api/auth/admin/users/${encodeURIComponent(username)}`, {
    method: "DELETE",
  });
}
