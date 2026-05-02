import os
import sys
import logging
from urllib.parse import urlparse

# Thêm root dir vào sys.path để import được các module của dự án
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.postgres import _get_pool
from models.article import MarketImpact

logging.basicConfig(level=logging.INFO, format='[MonitorAgent] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MonitorAgent:
    """
    Giám thị mã nguồn mở (Executable Monitor Agent).
    Chịu trách nhiệm audit tự động toàn bộ dự án để đảm bảo AI (tôi) không đi chệch hướng.
    """
    
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def run_audit(self):
        logger.info("Bắt đầu Audit Toàn Diện...")
        self._check_environment()
        self._check_architecture()
        self._check_database_integrity()
        
        logger.info(f"Kết thúc Audit: {self.errors} Lỗi nghiêm trọng, {self.warnings} Cảnh báo.")
        if self.errors > 0:
            logger.error("❌ DỰ ÁN ĐANG SAI LỆCH YÊU CẦU LÕI! Cần sửa ngay.")
            sys.exit(1)
        else:
            logger.info("✅ Kiến trúc và Data Integrity hoàn toàn tuân thủ.")

    def _check_environment(self):
        logger.info("Kiểm tra Environment Variables...")
        required_keys = ["DATABASE_URL"] # Không check GROQ và BOT_TOKEN ở CI để tránh lộ
        for key in required_keys:
            if not os.environ.get(key):
                logger.warning(f"Thiếu {key}. Nếu chạy trên CI/CD, có thể gây lỗi DB.")
                self.warnings += 1
                
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url and "pooler.supabase.com" not in db_url and "localhost" not in db_url:
            logger.warning("DATABASE_URL dường như đang dùng kết nối trực tiếp (IPv6) thay vì Pooler. Có thể gây lỗi trên GitHub Actions.")
            self.warnings += 1

    def _check_architecture(self):
        logger.info("Kiểm tra Kiến trúc (Zero Bloat)...")
        # Đảm bảo không tồn tại module sqlite cũ
        if os.path.exists("storage/sqlite.py"):
            logger.error("Phát hiện tàn dư của SQLite. Vi phạm quy tắc Lean/Zero Bloat.")
            self.errors += 1
            
        # Đảm bảo file cấu trúc đúng
        if not os.path.exists("models/article.py"):
            logger.error("Thiếu Data Contract trung tâm (models/article.py).")
            self.errors += 1

    def _check_database_integrity(self):
        logger.info("Kiểm tra Data Integrity trong Database...")
        pool = _get_pool()
        if not pool:
            logger.warning("Không thể kết nối DB để audit data. Bỏ qua.")
            return

        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                # 1. Chống Duplicate: Kiểm tra xem có url nào bị trùng hash (id) không
                cur.execute("SELECT id, COUNT(*) FROM articles GROUP BY id HAVING COUNT(*) > 1;")
                dups = cur.fetchall()
                if dups:
                    logger.error(f"PHÁT HIỆN DUPLICATE ID TRONG DB: {len(dups)} bản ghi bị trùng!")
                    self.errors += 1
                    
                # 2. Kiểm tra tính hợp lệ của AI Output (Market Impact)
                valid_impacts = [e.value for e in MarketImpact]
                cur.execute("SELECT id, market_impact FROM articles WHERE processed = TRUE;")
                processed_articles = cur.fetchall()
                
                bad_impacts = 0
                for a_id, impact in processed_articles:
                    if impact not in valid_impacts:
                        logger.error(f"Bài báo {a_id} có market_impact rác từ LLM: '{impact}'. Vi phạm Enum contract!")
                        bad_impacts += 1
                        self.errors += 1
                
                if bad_impacts == 0:
                    logger.info("Kiểm tra Enum MarketImpact: Đạt chuẩn 100%. Không có rác LLM.")
                
                # 3. FinOps: Đảm bảo không có bài nào bị kẹt retry quá số lần cho phép
                cur.execute("SELECT COUNT(*) FROM articles WHERE retry_count > 3;")
                stuck = cur.fetchone()[0]
                if stuck > 0:
                    logger.warning(f"FinOps Warning: Có {stuck} bài báo bị kẹt (retry > 3). Cần kiểm tra prompt hoặc rate limit.")
                    self.warnings += 1
                    
        except Exception as e:
            logger.error(f"Lỗi khi audit DB: {e}")
            self.errors += 1
        finally:
            pool.putconn(conn)

if __name__ == "__main__":
    agent = MonitorAgent()
    agent.run_audit()
