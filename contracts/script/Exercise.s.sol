// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {GridixEscrow} from "../src/GridixEscrow.sol";
import {GridixStaking} from "../src/GridixStaking.sol";
import {MockUSDC} from "../test/mocks/MockUSDC.sol";

/// @notice Exercises every function of both contracts with real on-chain transactions on
///         Sepolia. Uses a freshly deployed MockUSDC and fresh contracts with the deployer
///         holding all roles (the production deployments use Circle USDC + separate roles; those
///         can't be token-exercised without USDC + the other role keys). Same contract code.
///         Each state-changing call below is a separate broadcast transaction.
contract Exercise is Script {
    uint256 constant USDC = 1e6;

    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address me = vm.addr(pk);
        address other = address(0xBEEF);

        vm.startBroadcast(pk);

        // ── deploys (3 tx) ──
        MockUSDC usdc = new MockUSDC();
        GridixEscrow escrow = new GridixEscrow(address(usdc), me, me, me); // admin+coordinator = me
        GridixStaking staking = new GridixStaking(address(usdc), me, me, me, me, 100 * USDC, 0);

        // ── setup (2 tx) ──
        usdc.mint(me, 1000 * USDC);
        usdc.approve(address(escrow), type(uint256).max);

        // ── escrow flow (3 tx) ──
        escrow.deposit(100 * USDC);
        escrow.debit(me, 30 * USDC); // coordinator debits -> treasury(me)
        escrow.withdraw(70 * USDC);

        // ── staking flow (9 tx) ──
        usdc.approve(address(staking), type(uint256).max);
        staking.stake(200 * USDC);
        staking.depositSettlement(50 * USDC);
        address[] memory ps = new address[](2);
        uint256[] memory amts = new uint256[](2);
        ps[0] = me;
        ps[1] = other;
        amts[0] = 20 * USDC;
        amts[1] = 10 * USDC;
        staking.settleBatch(ps, amts); // batch to 2 providers, 1 tx
        staking.withdraw(); // provider (me) withdraws own earnings
        staking.slash(me, 50 * USDC, keccak256("evidence-session10")); // held dispute
        staking.resolveDispute(me, false); // overturned -> stake returned
        staking.unstake(100 * USDC); // cooldown 0 for the exercise
        staking.completeUnstake(); // claim

        vm.stopBroadcast();

        console.log("MockUSDC:      ", address(usdc));
        console.log("GridixEscrow:  ", address(escrow));
        console.log("GridixStaking: ", address(staking));
        console.log("escrow bal(me):", escrow.balanceOf(me));
        console.log("stake(me):     ", staking.stakeOf(me));
        console.log("earnings(other):", staking.earningsOf(other));
    }
}
