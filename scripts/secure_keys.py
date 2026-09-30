from relay.envfile import candidate_files, parse
from relay.memory.secrets import save_secret


def migrate_env():
    for env_path in candidate_files():
        if not env_path.exists():
            continue
            
        text = env_path.read_text(encoding="utf-8-sig")
        values = parse(text)
        migrated = False
        
        # Check for sensitive keys
        sensitive_keys = ["RELAY_LLM_KEY", "SARVAM_API_KEY", "RELAY_LLM_URL"]
        for key in sensitive_keys:
            if key in values and values[key]:
                save_secret(key, values[key])
                print(f"Migrated {key} to secure DPAPI storage.")
                migrated = True
                
        if migrated:
            # Redact the .env file
            new_lines = []
            for line in text.splitlines():
                if any(line.strip().startswith(k + "=") for k in sensitive_keys):
                    k = line.split("=")[0].strip()
                    new_lines.append(f"{k}=# REDACTED - MOVED TO SECURE STORAGE")
                else:
                    new_lines.append(line)
            
            # Write back
            env_path.write_text("\n".join(new_lines), encoding="utf-8-sig")
            print(f"Redacted secrets in {env_path}")
            
            # Restrict permissions (Windows)
            import subprocess
            try:
                # Remove inheritance and copy current ACL
                subprocess.run(['icacls', str(env_path), '/inheritance:d'], check=True, capture_output=True)
                # Remove BUILTIN\Users
                subprocess.run(['icacls', str(env_path), '/remove', 'Users'], check=True, capture_output=True)
                subprocess.run(['icacls', str(env_path), '/remove', 'Authenticated Users'], check=True, capture_output=True)
                print(f"Restricted permissions for {env_path}")
            except Exception as e:
                print(f"Warning: could not restrict permissions: {e}")

if __name__ == "__main__":
    migrate_env()
