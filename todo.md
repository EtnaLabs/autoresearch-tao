## Deploy to Bittensor Testnet

1. Install tools

```
pip install bittensor btcli
```

2. Create wallets

```
btcli wallet create --wallet.name owner --wallet.hotkey default
btcli wallet create --wallet.name validator --wallet.hotkey default
btcli wallet create --wallet.name miner --wallet.hotkey default
```

3. Get test TAO

Get the owner coldkey address:
```
btcli wallet overview --wallet.name owner --subtensor.network test
```
Go to the Bittensor Discord and request ~100+ test TAO to that address (there's no working faucet right now).

4. Create your subnet

```
btcli subnet create --wallet.name owner --subtensor.network test
```
Note the netuid it returns. New subnets take ~1 week to activate.

5. Fund validator & miner wallets

Transfer some test TAO from owner to each:
```
btcli wallet transfer --wallet.name owner --dest <VALIDATOR_COLDKEY_SS58> --amount 10 --subtensor.network test
btcli wallet transfer --wallet.name owner --dest <MINER_COLDKEY_SS58> --amount 10 --subtensor.network test
```

6. Register on the subnet

```
btcli subnet register --netuid <NETUID> --subtensor.network test --wallet.name validator --wallet.hotkey default
btcli subnet register --netuid <NETUID> --subtensor.network test --wallet.name miner --wallet.hotkey default
```

7. Prepare training data

```
python prepare_lite.py
```

8. Start the miner

```
python miner.py \
  --netuid <NETUID> \
  --wallet.name miner \
  --wallet.hotkey default \
  --miner-id raven \
  --time-budget 15
```
Optionally add `--reward-wallet <SS58_ADDRESS>` to send rewards to a different wallet.

9. Start the validator

```
python validator.py \
  --netuid <NETUID> \
  --wallet.name validator \
  --wallet.hotkey default \
  --interval 60
```

10. Start the UI (optional)

```
cd ui && npm run dev
```

---

**Key gotchas:**
- Subnet activation delay is ~1 week after creation — nothing will work until then
- Both miner and validator must be registered before running the scripts
- The miner's axon port (default 8091) must be reachable from the validator — open firewall/port-forward if needed
- Use `--axon.external_ip` and `--axon.external_port` on the miner if behind NAT
