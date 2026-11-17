use std::{env, net::SocketAddr, sync::Arc, time::Duration};
use argon2::{Argon2, PasswordHash, PasswordHasher, PasswordVerifier, password_hash::SaltString};
use axum::{Router, body::{Body, to_bytes}, extract::{Request, State}, http::{HeaderMap, HeaderValue, Method, StatusCode, header}, response::{IntoResponse, Response}, routing::{any, get, post}};
use rand::{RngCore, rngs::OsRng};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Row, postgres::PgPoolOptions};
use subtle::ConstantTimeEq;
use tower_http::services::{ServeDir, ServeFile};
use uuid::Uuid;

#[derive(Clone)]
struct App { db: PgPool, client: reqwest::Client, worker: String, key: String, origin: String, secure: bool, passwords: Arc<tokio::sync::Semaphore>, dummy: String }

struct Actor { id: String, username: String, role: String, must_change: bool, timezone: String, csrf: String, mcp: bool, can_write: bool }

impl Actor {
 fn public(&self)->Value { json!({"id":self.id,"username":self.username,"role":self.role,"must_change":self.must_change,"timezone":self.timezone,"csrf_token":self.csrf}) }
}

type Failure=(StatusCode,axum::Json<Value>);
fn fail(status:StatusCode,message:&str)->Failure {(status,axum::Json(json!({"detail":message})))}
fn db_error(_:sqlx::Error)->Failure {fail(StatusCode::SERVICE_UNAVAILABLE,"Chưa kết nối được cơ sở dữ liệu.")}
fn secret()->String {let mut bytes=[0u8;32];OsRng.fill_bytes(&mut bytes);bytes.iter().map(|b|format!("{b:02x}")).collect()}
fn digest(value:&str)->String {format!("{:x}",Sha256::digest(value.as_bytes()))}
fn cookie(headers:&HeaderMap)->Option<String> {headers.get(header::COOKIE)?.to_str().ok()?.split(';').find_map(|part|part.trim().strip_prefix("pm_session=").map(str::to_owned))}
fn origin_ok(app:&App,headers:&HeaderMap)->bool {headers.get(header::ORIGIN).and_then(|v|v.to_str().ok())==Some(app.origin.as_str())}
fn cookie_header(app:&App,value:&str,age:u32)->HeaderValue {HeaderValue::from_str(&format!("pm_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{}",if app.secure{"; Secure"}else{""})).unwrap()}

async fn body_json(req:Request)->Result<Value,Failure> {
 let bytes=to_bytes(req.into_body(),65_536).await.map_err(|_|fail(StatusCode::PAYLOAD_TOO_LARGE,"Dữ liệu quá lớn."))?;
 serde_json::from_slice(&bytes).map_err(|_|fail(StatusCode::BAD_REQUEST,"Dữ liệu không hợp lệ."))
}

// Body is Send but not Sync; borrow only Sync request metadata across DB awaits.
async fn actor(app:&App,headers:&HeaderMap,method:&Method)->Result<Actor,Failure> {
 if let Some(token)=headers.get(header::AUTHORIZATION).and_then(|v|v.to_str().ok()).and_then(|v|v.strip_prefix("Bearer ")) {
  if token.len()>128 {return Err(fail(StatusCode::UNAUTHORIZED,"MCP token không hợp lệ."))}
  let row=sqlx::query("SELECT u.id,u.username,u.role,u.must_change,u.timezone,t.can_write FROM pm_mcp_tokens t JOIN pm_users u ON u.id=t.user_id WHERE t.digest=$1 AND t.revoked_at IS NULL AND t.expires_at>now() AND u.active AND NOT u.must_change")
    .bind(digest(token)).fetch_optional(&app.db).await.map_err(db_error)?.ok_or_else(||fail(StatusCode::UNAUTHORIZED,"MCP token hết hạn hoặc đã thu hồi."))?;
  sqlx::query("UPDATE pm_mcp_tokens SET last_used_at=now() WHERE digest=$1").bind(digest(token)).execute(&app.db).await.map_err(db_error)?;
  return Ok(Actor{id:row.get("id"),username:row.get("username"),role:row.get("role"),must_change:row.get("must_change"),timezone:row.get("timezone"),csrf:String::new(),mcp:true,can_write:row.get("can_write")});
 }
 let token=cookie(headers).filter(|s|s.len()==64).ok_or_else(||fail(StatusCode::UNAUTHORIZED,"Đăng nhập để tiếp tục."))?;
 let row=sqlx::query("SELECT u.id,u.username,u.role,u.must_change,u.timezone,s.csrf FROM pm_sessions s JOIN pm_users u ON u.id=s.user_id WHERE s.digest=$1 AND s.expires_at>now() AND s.last_seen>now()-interval '30 minutes' AND u.active")
  .bind(digest(&token)).fetch_optional(&app.db).await.map_err(db_error)?.ok_or_else(||fail(StatusCode::UNAUTHORIZED,"Phiên đăng nhập đã hết hạn."))?;
 let a=Actor{id:row.get("id"),username:row.get("username"),role:row.get("role"),must_change:row.get("must_change"),timezone:row.get("timezone"),csrf:row.get("csrf"),mcp:false,can_write:true};
 if method!=Method::GET && method!=Method::HEAD {
  let supplied=headers.get("x-csrf-token").and_then(|v|v.to_str().ok()).unwrap_or("");
  if !origin_ok(app,headers)||!bool::from(supplied.as_bytes().ct_eq(a.csrf.as_bytes())) {return Err(fail(StatusCode::FORBIDDEN,"Phiên thao tác không hợp lệ. Tải lại trang."))}
 }
 sqlx::query("UPDATE pm_sessions SET last_seen=now() WHERE digest=$1").bind(digest(&token)).execute(&app.db).await.map_err(db_error)?;
 Ok(a)
}

async fn new_session(app:&App,id:&str,expected:&str)->Result<(String,String),Failure> {
 let raw=secret();let csrf=secret();
 let mut tx=app.db.begin().await.map_err(db_error)?;
 let hash:Option<String>=sqlx::query_scalar("SELECT password_hash FROM pm_users WHERE id=$1 AND active FOR UPDATE").bind(id).fetch_optional(&mut *tx).await.map_err(db_error)?;
 if hash.as_deref()!=Some(expected) {return Err(fail(StatusCode::UNAUTHORIZED,"Tài khoản đã thay đổi. Đăng nhập lại."))}
 sqlx::query("DELETE FROM pm_sessions WHERE expires_at<now() OR last_seen<now()-interval '30 minutes'").execute(&mut *tx).await.map_err(db_error)?;
 sqlx::query("INSERT INTO pm_sessions(digest,user_id,csrf,expires_at) VALUES($1,$2,$3,now()+interval '12 hours')").bind(digest(&raw)).bind(id).bind(&csrf).execute(&mut *tx).await.map_err(db_error)?;
 tx.commit().await.map_err(db_error)?;
 Ok((raw,csrf))
}

async fn login(State(app):State<App>,req:Request)->Result<Response,Failure> {
 if !origin_ok(&app,req.headers()) {return Err(fail(StatusCode::FORBIDDEN,"Nguồn đăng nhập không hợp lệ."))}
 let peer=req.extensions().get::<axum::extract::ConnectInfo<SocketAddr>>().map(|v|v.0.ip().to_string()).unwrap_or_default();
 let value=body_json(req).await?;
 let username=value["username"].as_str().unwrap_or("").to_ascii_lowercase();let password=value["password"].as_str().unwrap_or("").to_owned();
 if username.len()>32 || password.len()>1024 {return Err(fail(StatusCode::UNAUTHORIZED,"Tên đăng nhập hoặc mật khẩu không đúng."))}
 let key=digest(&format!("{peer}:{username}"));
 let attempts:i32=sqlx::query_scalar("INSERT INTO pm_login_limits(key) VALUES($1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN pm_login_limits.window_start<now()-interval '10 minutes' THEN 1 ELSE pm_login_limits.attempts+1 END,window_start=CASE WHEN pm_login_limits.window_start<now()-interval '10 minutes' THEN now() ELSE pm_login_limits.window_start END RETURNING attempts")
  .bind(&key).fetch_one(&app.db).await.map_err(db_error)?;
 if attempts>10 {return Err(fail(StatusCode::TOO_MANY_REQUESTS,"Thử đăng nhập lại sau ít phút."))}
 let row=sqlx::query("SELECT id,username,password_hash,role,must_change,timezone FROM pm_users WHERE username=$1 AND active").bind(&username).fetch_optional(&app.db).await.map_err(db_error)?;
 let hash=row.as_ref().map(|r|r.get::<String,_>("password_hash")).unwrap_or(app.dummy.clone());
 let expected=hash.clone();
 let permit=tokio::time::timeout(Duration::from_secs(5),app.passwords.clone().acquire_owned()).await.map_err(|_|fail(StatusCode::TOO_MANY_REQUESTS,"Máy chủ đang bận. Thử lại sau."))?.map_err(|_|fail(StatusCode::SERVICE_UNAVAILABLE,"Máy chủ đang dừng."))?;
 let valid=tokio::task::spawn_blocking(move||{let _permit=permit;PasswordHash::new(&hash).ok().map(|h|Argon2::default().verify_password(password.as_bytes(),&h).is_ok()).unwrap_or(false)}).await.unwrap_or(false);
 if !valid||row.is_none() {return Err(fail(StatusCode::UNAUTHORIZED,"Tên đăng nhập hoặc mật khẩu không đúng."))}
 let row=row.unwrap();let id:String=row.get("id");
 let unchanged:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM pm_users WHERE id=$1 AND active AND password_hash=$2)").bind(&id).bind(&expected).fetch_one(&app.db).await.map_err(db_error)?;
 if !unchanged {return Err(fail(StatusCode::UNAUTHORIZED,"Tài khoản đã thay đổi. Đăng nhập lại."))}
 let (raw,csrf)=new_session(&app,&id,&expected).await?;
 sqlx::query("DELETE FROM pm_login_limits WHERE key=$1 OR window_start<now()-interval '1 day'").bind(key).execute(&app.db).await.map_err(db_error)?;
 sqlx::query("INSERT INTO pm_sync_requests(user_id) VALUES($1) ON CONFLICT(user_id) DO UPDATE SET requested_at=now(),status=CASE WHEN pm_sync_requests.status='running' THEN 'running' ELSE 'pending' END").bind(&id).execute(&app.db).await.map_err(db_error)?;
 let a=Actor{id,username:row.get("username"),role:row.get("role"),must_change:row.get("must_change"),timezone:row.get("timezone"),csrf,mcp:false,can_write:true};
 let mut response=axum::Json(json!({"user":a.public()})).into_response();response.headers_mut().insert(header::SET_COOKIE,cookie_header(&app,&raw,43200));Ok(response)
}

async fn auth_routes(State(app):State<App>,req:Request)->Result<Response,Failure> {
 let a=actor(&app,req.headers(),req.method()).await?;
 if a.mcp {return Err(fail(StatusCode::FORBIDDEN,"Dùng phiên đăng nhập để quản lý tài khoản."))}
 let path=req.uri().path().to_owned();
 if path=="/api/auth/me"&&req.method()==Method::GET {return Ok(axum::Json(json!({"user":a.public()})).into_response())}
 if path=="/api/auth/logout"&&req.method()==Method::POST {
  if let Some(raw)=cookie(req.headers()) {sqlx::query("DELETE FROM pm_sessions WHERE digest=$1").bind(digest(&raw)).execute(&app.db).await.map_err(db_error)?;}
  let mut r=axum::Json(json!({"ok":true})).into_response();r.headers_mut().insert(header::SET_COOKIE,cookie_header(&app,"",0));return Ok(r)
 }
 if path!="/api/auth/password"||req.method()!=Method::POST {return Err(fail(StatusCode::NOT_FOUND,"Không có chức năng này."))}
 let value=body_json(req).await?;let old=value["old_password"].as_str().unwrap_or("").to_owned();let new=value["new_password"].as_str().unwrap_or("").to_owned();
 if !(12..=1024).contains(&new.len())||new==old {return Err(fail(StatusCode::UNPROCESSABLE_ENTITY,"Mật khẩu mới cần ít nhất 12 ký tự và khác mật khẩu cũ."))}
 let current:String=sqlx::query_scalar("SELECT password_hash FROM pm_users WHERE id=$1 AND active").bind(&a.id).fetch_one(&app.db).await.map_err(db_error)?;
 let original=current.clone();
 let permit=tokio::time::timeout(Duration::from_secs(5),app.passwords.clone().acquire_owned()).await.map_err(|_|fail(StatusCode::TOO_MANY_REQUESTS,"Thử lại sau ít phút."))?.map_err(|_|fail(StatusCode::SERVICE_UNAVAILABLE,"Máy chủ đang dừng."))?;
 let hashed=tokio::task::spawn_blocking(move||{let _permit=permit;let parsed=PasswordHash::new(&current).ok()?;Argon2::default().verify_password(old.as_bytes(),&parsed).ok()?;Argon2::default().hash_password(new.as_bytes(),&SaltString::generate(&mut OsRng)).ok().map(|p|p.to_string())}).await.ok().flatten().ok_or_else(||fail(StatusCode::UNAUTHORIZED,"Mật khẩu hiện tại không đúng."))?;
 let mut tx=app.db.begin().await.map_err(db_error)?;
 let changed=sqlx::query("UPDATE pm_users SET password_hash=$1,must_change=FALSE WHERE id=$2 AND active AND password_hash=$3").bind(&hashed).bind(&a.id).bind(original).execute(&mut *tx).await.map_err(db_error)?;
 if changed.rows_affected()!=1 {return Err(fail(StatusCode::CONFLICT,"Tài khoản đã thay đổi. Đăng nhập lại."))}
 sqlx::query("DELETE FROM pm_sessions WHERE user_id=$1").bind(&a.id).execute(&mut *tx).await.map_err(db_error)?;
 sqlx::query("UPDATE pm_mcp_tokens SET revoked_at=now() WHERE user_id=$1").bind(&a.id).execute(&mut *tx).await.map_err(db_error)?;
 tx.commit().await.map_err(db_error)?;
 let (raw,csrf)=new_session(&app,&a.id,&hashed).await?;
 let mut response=axum::Json(json!({"user":Actor{csrf,must_change:false,..a}.public()})).into_response();response.headers_mut().insert(header::SET_COOKIE,cookie_header(&app,&raw,43200));Ok(response)
}

async fn account(State(app):State<App>,req:Request)->Result<Response,Failure> {
 let a=actor(&app,req.headers(),req.method()).await?;
 if a.mcp||a.must_change {return Err(fail(StatusCode::FORBIDDEN,"Đăng nhập và đổi mật khẩu trước khi quản lý MCP token."))}
 let path=req.uri().path().to_owned();let method=req.method().clone();
 if method==Method::GET {
  let rows:Vec<Value>=sqlx::query("SELECT id,label,can_write,created_at::text,expires_at::text,revoked_at::text,last_used_at::text FROM pm_mcp_tokens WHERE user_id=$1 ORDER BY created_at DESC LIMIT 100").bind(&a.id).fetch_all(&app.db).await.map_err(db_error)?.iter().map(|r|json!({"id":r.get::<String,_>("id"),"label":r.get::<String,_>("label"),"can_write":r.get::<bool,_>("can_write"),"created_at":r.get::<String,_>("created_at"),"expires_at":r.get::<String,_>("expires_at"),"revoked_at":r.get::<Option<String>,_>("revoked_at"),"last_used_at":r.get::<Option<String>,_>("last_used_at")})).collect();
  return Ok(axum::Json(json!({"items":rows,"mcp_url":format!("{}/mcp",app.origin)})).into_response())
 }
 if method==Method::DELETE {
  let id=path.rsplit('/').next().unwrap_or("");
  let changed=sqlx::query("UPDATE pm_mcp_tokens SET revoked_at=now() WHERE id=$1 AND user_id=$2").bind(id).bind(&a.id).execute(&app.db).await.map_err(db_error)?;
  if changed.rows_affected()==0 {return Err(fail(StatusCode::NOT_FOUND,"Không có MCP token trong kho này."))}
  return Ok(axum::Json(json!({"ok":true})).into_response())
 }
 if method==Method::PATCH {
  let id=path.rsplit('/').next().unwrap_or("").to_owned();let value=body_json(req).await?;
  let can_write=value["can_write"].as_bool().ok_or_else(||fail(StatusCode::UNPROCESSABLE_ENTITY,"Chọn quyền kết nối MCP."))?;
  let changed=sqlx::query("UPDATE pm_mcp_tokens SET can_write=$1 WHERE id=$2 AND user_id=$3 AND revoked_at IS NULL AND expires_at>now()")
   .bind(can_write).bind(&id).bind(&a.id).execute(&app.db).await.map_err(db_error)?;
  if changed.rows_affected()==0 {return Err(fail(StatusCode::NOT_FOUND,"Không có MCP token còn hiệu lực trong kho này."))}
  return Ok(axum::Json(json!({"ok":true,"can_write":can_write})).into_response())
 }
 if method!=Method::POST {return Err(fail(StatusCode::METHOD_NOT_ALLOWED,"Thao tác không được hỗ trợ."))}
 let value=body_json(req).await?;let label=value["label"].as_str().unwrap_or("").trim();
 if label.is_empty()||label.len()>100 {return Err(fail(StatusCode::UNPROCESSABLE_ENTITY,"Nhập tên kết nối MCP."))}
 let can_write=match value.get("can_write") {None=>true,Some(v)=>v.as_bool().ok_or_else(||fail(StatusCode::UNPROCESSABLE_ENTITY,"Quyền MCP không hợp lệ."))?};
 let days=value["days"].as_i64().unwrap_or(30).clamp(1,90);let raw=secret();let id=Uuid::new_v4().to_string();
 sqlx::query("INSERT INTO pm_mcp_tokens(id,user_id,digest,label,can_write,expires_at) VALUES($1,$2,$3,$4,$5,now()+$6*interval '1 day')").bind(&id).bind(&a.id).bind(digest(&raw)).bind(label).bind(can_write).bind(days as f64).execute(&app.db).await.map_err(db_error)?;
 Ok(axum::Json(json!({"id":id,"token":raw,"can_write":can_write,"mcp_url":format!("{}/mcp",app.origin)})).into_response())
}

async fn admin(State(app):State<App>,req:Request)->Result<Response,Failure> {
 let a=actor(&app,req.headers(),req.method()).await?;
 if a.mcp||a.must_change||a.role!="admin" {return Err(fail(StatusCode::FORBIDDEN,"Chỉ quản trị viên được quản lý tài khoản."))}
 if req.method()==Method::GET {
  let rows=sqlx::query("SELECT id,username,role,active,must_change,timezone FROM pm_users ORDER BY username").fetch_all(&app.db).await.map_err(db_error)?;
  return Ok(axum::Json(json!({"items":rows.iter().map(|r|json!({"id":r.get::<String,_>("id"),"username":r.get::<String,_>("username"),"role":r.get::<String,_>("role"),"active":r.get::<bool,_>("active"),"must_change":r.get::<bool,_>("must_change"),"timezone":r.get::<String,_>("timezone")})).collect::<Vec<_>>(),"max_users":20})).into_response())
 }
 if req.method()!=Method::PATCH {return Err(fail(StatusCode::METHOD_NOT_ALLOWED,"Thao tác không được hỗ trợ."))}
 let target=req.uri().path().rsplit('/').next().unwrap_or("").to_owned();let value=body_json(req).await?;
 let password=if value["reset_password"]==true {if a.id==target{return Err(fail(StatusCode::CONFLICT,"Dùng chức năng đổi mật khẩu cá nhân."))}Some(secret())}else{None};
 let hash=if let Some(p)=password.clone(){Some(tokio::task::spawn_blocking(move||Argon2::default().hash_password(p.as_bytes(),&SaltString::generate(&mut OsRng)).unwrap().to_string()).await.map_err(|_|fail(StatusCode::INTERNAL_SERVER_ERROR,"Chưa tạo được mật khẩu."))?)}else{None};
 let mut tx=app.db.begin().await.map_err(db_error)?;sqlx::query("SELECT pg_advisory_xact_lock(80208020)").execute(&mut *tx).await.map_err(db_error)?;
 let row=sqlx::query("SELECT username,role,active FROM pm_users WHERE id=$1 FOR UPDATE").bind(&target).fetch_optional(&mut *tx).await.map_err(db_error)?.ok_or_else(||fail(StatusCode::NOT_FOUND,"Không có tài khoản này."))?;
 let role=value["role"].as_str().unwrap_or(row.get("role"));let active=value["active"].as_bool().unwrap_or(row.get("active"));let username=value["username"].as_str().unwrap_or(row.get("username"));
 if !["admin","owner"].contains(&role)||username.len()<3||username.len()>32||!username.bytes().all(|b|b.is_ascii_lowercase()||b.is_ascii_digit()||b==b'_'||b==b'-') {return Err(fail(StatusCode::UNPROCESSABLE_ENTITY,"Tên tài khoản hoặc quyền không hợp lệ."))}
 let admins:i64=sqlx::query_scalar("SELECT COUNT(*) FROM pm_users WHERE role='admin' AND active AND id<>$1").bind(&target).fetch_one(&mut *tx).await.map_err(db_error)?;
 if row.get::<String,_>("role")=="admin"&&(!active||role!="admin")&&admins==0 {return Err(fail(StatusCode::CONFLICT,"Cần giữ ít nhất một quản trị viên hoạt động."))}
 sqlx::query("UPDATE pm_users SET username=$1,role=$2,active=$3,password_hash=COALESCE($4,password_hash),must_change=CASE WHEN $4 IS NULL THEN must_change ELSE TRUE END WHERE id=$5").bind(username).bind(role).bind(active).bind(hash).bind(&target).execute(&mut *tx).await.map_err(db_error)?;
 sqlx::query("DELETE FROM pm_sessions WHERE user_id=$1").bind(&target).execute(&mut *tx).await.map_err(db_error)?;
 sqlx::query("UPDATE pm_mcp_tokens SET revoked_at=now() WHERE user_id=$1").bind(&target).execute(&mut *tx).await.map_err(db_error)?;
 tx.commit().await.map_err(db_error)?;
 Ok(axum::Json(json!({"ok":true,"temporary_password":password})).into_response())
}

async fn proxy(State(app):State<App>,req:Request)->Result<Response,Failure> {
 let a=actor(&app,req.headers(),req.method()).await?;let path=req.uri().path().to_owned();
 if a.must_change {return Err(fail(StatusCode::FORBIDDEN,"Đổi mật khẩu ban đầu trước khi dùng kho."))}
 if path=="/mcp"&&!a.mcp {return Err(fail(StatusCode::UNAUTHORIZED,"Dùng MCP token cá nhân để kết nối Codex hoặc Claude."))}
 if a.mcp&&path!="/mcp"&&req.method()!=Method::GET&&!a.can_write {return Err(fail(StatusCode::FORBIDDEN,"MCP token chỉ có quyền đọc."))}
 if a.mcp && path!="/mcp" && req.method()!=Method::GET {
  let parts:Vec<&str>=path.trim_start_matches('/').split('/').collect();
  let reel_id=parts.get(2).and_then(|s|s.parse::<u64>().ok()).is_some_and(|id|id>0);
  let page_id=parts.get(2).is_some_and(|id|!id.is_empty()&&id.len()<=32&&id.bytes().all(|b|b.is_ascii_digit()));
  let allowed=(req.method()==Method::POST && ["/api/reels","/api/reels/now","/api/analytics/sync"].contains(&path.as_str()))
   || (req.method()==Method::POST && ["/api/connections","/api/reels/assets"].contains(&path.as_str()))
   || (parts.first()==Some(&"api") && parts.get(1)==Some(&"connections") && reel_id &&
      ((parts.len()==3 && req.method()==Method::PUT) || (parts.len()==4 && req.method()==Method::POST && ["check","sync","disconnect"].contains(&parts[3]))))
   || (parts.first()==Some(&"api") && parts.get(1)==Some(&"pages") && page_id &&
      ((parts.len()==3 && req.method()==Method::PATCH) || (parts.len()==4 && req.method()==Method::POST && ["refresh","edit-options","edit"].contains(&parts[3]))))
   || (parts.first()==Some(&"api") && parts.get(1)==Some(&"reels") && reel_id &&
      ((parts.len()==3 && req.method()==Method::PATCH) || (parts.len()==4 && req.method()==Method::POST && ["cancel","resume","verify"].contains(&parts[3]))));
  if !allowed {return Err(fail(StatusCode::FORBIDDEN,"MCP token không được phép thực hiện thao tác này."))}
 }
 let method=req.method().clone();let route=req.uri().path_and_query().map(|p|p.as_str()).unwrap_or("/").to_owned();
 let mut upstream=app.client.request(method.clone(),format!("{}{}",app.worker,route)).header("x-pm-internal",&app.key).header("x-pm-workspace",&a.id).header("x-pm-capability",if a.can_write{"write"}else{"read"});
 for name in ["content-type","content-length","x-filename","range","if-range","accept"] {if let Some(value)=req.headers().get(name){upstream=upstream.header(name,value);}}
 let request_body=if path=="/api/reels/assets" && method==Method::POST {
  reqwest::Body::wrap_stream(req.into_body().into_data_stream())
 } else {
  let bytes=to_bytes(req.into_body(),128_000).await.map_err(|_|fail(StatusCode::PAYLOAD_TOO_LARGE,"Dữ liệu quá lớn."))?;
  reqwest::Body::from(bytes)
 };
 let result=upstream.body(request_body).send().await.map_err(|_|fail(StatusCode::BAD_GATEWAY,"Dịch vụ Meta chưa sẵn sàng. Thử lại sau."))?;
 let status=result.status();let headers=result.headers().clone();
 if method!=Method::GET {let _=sqlx::query("INSERT INTO pm_audit(user_id,action,status) VALUES($1,$2,$3)").bind(&a.id).bind(if path=="/mcp"{"mcp_request"}else{"api_write"}).bind(status.as_u16() as i32).execute(&app.db).await;}
 let mut response=Response::new(Body::from_stream(result.bytes_stream()));*response.status_mut()=status;
 for name in ["content-type","content-length","content-range","accept-ranges","cache-control","content-disposition","x-accel-buffering"] {if let Some(value)=headers.get(name){response.headers_mut().insert(name,value.clone());}}
 Ok(response)
}

async fn health(State(app):State<App>)->Response {
 let db=sqlx::query("SELECT 1").execute(&app.db).await.is_ok();
 let worker=app.client.get(format!("{}/health",app.worker)).header("x-pm-internal",&app.key).timeout(Duration::from_secs(5)).send().await.map(|r|r.status().is_success()).unwrap_or(false);
 (if db&&worker{StatusCode::OK}else{StatusCode::SERVICE_UNAVAILABLE},axum::Json(json!({"ok":db&&worker,"database":db,"worker":worker}))).into_response()
}

#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>> {
 dotenvy::dotenv().ok();
 let db=PgPoolOptions::new().max_connections(12).connect(&env::var("DATABASE_URL")?).await?;
 sqlx::raw_sql(include_str!("../../migrations/001.sql")).execute(&db).await?;
 let origin=env::var("PM_PUBLIC_ORIGIN").unwrap_or("http://127.0.0.1:8020".into());
 let key=env::var("PM_INTERNAL_KEY")?;if key.len()<48{return Err("PM_INTERNAL_KEY must be at least 48 characters".into())}
 let dummy=Argon2::default().hash_password(secret().as_bytes(),&SaltString::generate(&mut OsRng)).map_err(|_|std::io::Error::other("Password hasher unavailable"))?.to_string();
 let app=App{db,client:reqwest::Client::builder().timeout(Duration::from_secs(900)).redirect(reqwest::redirect::Policy::none()).build()?,worker:env::var("PM_WORKER_URL").unwrap_or("http://127.0.0.1:8021".into()),key,origin,secure:env::var("PM_COOKIE_SECURE").is_ok_and(|v|v=="true"),passwords:Arc::new(tokio::sync::Semaphore::new(4)),dummy};
 let frontend=env::var("PM_FRONTEND_DIR").unwrap_or("frontend/dist".into());
 let router=Router::new().route("/healthz",get(health)).route("/api/auth/login",post(login)).route("/api/auth/{*path}",any(auth_routes)).route("/api/account/mcp-tokens",any(account)).route("/api/account/mcp-tokens/{id}",any(account)).route("/api/admin/users",any(admin)).route("/api/admin/users/{id}",any(admin)).route("/api/{*path}",any(proxy)).route("/mcp",post(proxy)).fallback_service(ServeDir::new(&frontend).not_found_service(ServeFile::new(format!("{frontend}/index.html")))).with_state(app)
 .layer(axum::middleware::map_response(|mut response:Response|async move {
  let headers=response.headers_mut();headers.insert("x-content-type-options",HeaderValue::from_static("nosniff"));headers.insert("referrer-policy",HeaderValue::from_static("no-referrer"));headers.insert("x-frame-options",HeaderValue::from_static("DENY"));headers.insert("content-security-policy",HeaderValue::from_static("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"));headers.insert("cache-control",HeaderValue::from_static("no-store"));response
 }));
 let addr=env::var("PM_LISTEN").unwrap_or("127.0.0.1:8020".into());let listener=tokio::net::TcpListener::bind(&addr).await?;println!("PageManager v2: {addr}");
 axum::serve(listener,router.into_make_service_with_connect_info::<SocketAddr>()).with_graceful_shutdown(async{let _=tokio::signal::ctrl_c().await;}).await?;Ok(())
}
