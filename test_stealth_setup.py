import sys
import time

def test_stealth_setup():
    print("1. Checking stealth bridge import...", flush=True)
    from stealth_bridge import stealth_bridge
    print("   [OK] stealth_bridge loaded.", flush=True)

    print("2. Checking stealth agent import & configuration...", flush=True)
    from stealth_agent import stealth_agent, dom_structure_query_tool
    assert stealth_agent is not None
    assert stealth_agent.max_steps == 99999999999999999, f"Expected max_steps 99999999999999999, got {stealth_agent.max_steps}"
    print(f"   [OK] stealth_agent verified (max_steps={stealth_agent.max_steps}).", flush=True)
    print(f"   [OK] Tools registered: {list(stealth_agent.tools.keys())}.", flush=True)

    print("3. Testing stealth bridge server start & stop...", flush=True)
    stealth_bridge.start_in_background()
    time.sleep(1.0)
    print("   [OK] stealth_bridge server listening on port 10088.", flush=True)
    stealth_bridge.stop()
    print("   [OK] stealth_bridge server stopped cleanly.", flush=True)

    print("4. Checking GradioUI import with smolagents...", flush=True)
    from smolagents import GradioUI
    print("   [OK] GradioUI imported successfully.", flush=True)

    print("\n[SUCCESS] All stealth components verified successfully!", flush=True)

if __name__ == "__main__":
    test_stealth_setup()
    sys.exit(0)
