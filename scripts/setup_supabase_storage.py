"""
Supabase Storage Setup Script.

Automates the creation of the market_data bucket and documents RLS policies.
"""

import sys
from loguru import logger

# Add src to path to import app modules
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from crypto_signals.config import get_settings
from crypto_signals.repository.supabase_storage import SupabaseStorageRepository

def setup():
    """
    Setup Supabase Storage for market data caching.
    """
    settings = get_settings()

    print("=== Supabase Storage Setup ===")

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        sys.exit(1)

    print(f"Target Project: {settings.SUPABASE_URL}")
    print(f"Bucket Name: {settings.SUPABASE_MARKET_DATA_BUCKET}")

    repo = SupabaseStorageRepository(settings.SUPABASE_MARKET_DATA_BUCKET)

    print("\nEnsuring bucket exists...")
    if repo.create_bucket_if_not_exists():
        print(f"✅ Bucket '{settings.SUPABASE_MARKET_DATA_BUCKET}' is ready.")
    else:
        print(f"❌ Failed to create/verify bucket '{settings.SUPABASE_MARKET_DATA_BUCKET}'.")
        sys.exit(1)

    print("\n--- Required Row Level Security (RLS) Policies ---")
    print("Run these SQL commands in the Supabase Dashboard SQL Editor:")
    print(f"""
-- 1. Allow authenticated users to read (SELECT) from the bucket
CREATE POLICY "Allow Authenticated Read"
ON storage.objects FOR SELECT
TO authenticated
USING (bucket_id = '{settings.SUPABASE_MARKET_DATA_BUCKET}');

-- 2. Allow service_role to manage all files (Already granted by default, but for documentation)
-- Service Role bypasses RLS by default. Ensure you use the service_role key in the backend.

-- 3. (Optional) Allow specific workers to INSERT/UPDATE if not using service_role
-- CREATE POLICY "Allow Backend Write"
-- ON storage.objects FOR INSERT
-- TO authenticated -- Or a specific role
-- WITH CHECK (bucket_id = '{settings.SUPABASE_MARKET_DATA_BUCKET}');
    """)

    print("Setup complete.")

if __name__ == "__main__":
    setup()
