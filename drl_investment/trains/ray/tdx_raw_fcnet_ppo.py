'''
refer to: https://github.com/ray-project/ray/blob/master/rllib/examples/custom_env.py
'''
import argparse
import os

import ray
from ray import air, tune
from ray.rllib.models import ModelCatalog
from ray.rllib.utils.test_utils import check_learning_achieved
from ray.tune.logger import pretty_print
from ray.tune.registry import get_trainable_cls

from drl_investment.models.ray.fc_net import TorchFC
from drl_investment.envs.tdx_raw import TDXRawEnv
from drl_investment.data.tdx import unpack_data

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=str, default=f"", help="The tdx stock data")
    parser.add_argument(
        "--run", type=str, default="PPO", help="The RLlib-registered algorithm to use."
    )
    parser.add_argument(
        "--framework",
        choices=["tf", "tf2", "torch"],
        default="torch",
        help="The DL framework specifier.",
    )
    parser.add_argument(
        "--as-test",
        action="store_true",
        help="Whether this script should be run as a test: --stop-reward must "
        "be achieved within --stop-timesteps AND --stop-iters.",
    )
    parser.add_argument(
        "--stop-iters", type=int, default=500000000, help="Number of iterations to train."
    )
    parser.add_argument(
        "--stop-timesteps", type=int, default=100000000, help="Number of timesteps to train."
    )
    parser.add_argument(
        "--stop-reward", type=float, default=100000000.0, help="Reward at which we stop training."
    )
    parser.add_argument(
        "--no-tune",
        action="store_true",
        help="Run without Tune using a manual train loop instead. In this case,"
        "use PPO without grid search and no TensorBoard.",
    )
    parser.add_argument(
        "--local-mode",
        action="store_true",
        help="Init Ray in local mode for easier debugging.",
    )

    args = parser.parse_args()

    return args


def config(args):
    pass


def main(args):
    pass


if __name__ == "__main__":

    args = parse_args()
    print(f"Running with following CLI options: {args}")
    
    ray.init(local_mode=args.local_mode)

    # Can also register the env creator function explicitly with:
    # register_env("corridor", lambda config: SimpleCorridor(config))
    ModelCatalog.register_custom_model(
        "my_model", TorchFC,
    )

    df = unpack_data(args.path)
    env_config = {
        'data': df.to_numpy(),
        'columns': df.columns.to_list(),
    }

    config = (
        get_trainable_cls(args.run)
        .get_default_config()
        # or "corridor" if registered above
        .environment(TDXRawEnv, env_config=env_config)
        .framework(args.framework)
        .rollouts(num_rollout_workers=1)
        .training(
            model={
                "custom_model": "my_model",
                "vf_share_layers": True,
            }
        )
        # Use GPUs iff `RLLIB_NUM_GPUS` env var set to > 0.
        .resources(num_gpus=int(os.environ.get("RLLIB_NUM_GPUS", "0")))
    )

    stop = {
        "training_iteration": args.stop_iters,
        "timesteps_total": args.stop_timesteps,
        "episode_reward_mean": args.stop_reward,
    }

    if args.no_tune:
        # manual training with train loop using PPO and fixed learning rate
        if args.run != "PPO":
            raise ValueError("Only support --run PPO with --no-tune.")
        print("Running manual train loop without Ray Tune.")
        # use fixed learning rate instead of grid search (needs tune)
        config.lr = 1e-3
        algo = config.build()
        # run manual training loop and print results after each iteration
        for _ in range(args.stop_iters):
            result = algo.train()
            # print(pretty_print(result))
            # stop training of the target train steps or reward are reached
            if (
                result["timesteps_total"] >= args.stop_timesteps
                or result["episode_reward_mean"] >= args.stop_reward
            ):
                break
        algo.stop()
    else:
        # automated run with Tune and grid search and TensorBoard
        print("Training automatically with Ray Tune")
        tuner = tune.Tuner(
            args.run,
            param_space=config.to_dict(),
            run_config=air.RunConfig(stop=stop),
        )
        results = tuner.fit()

        if args.as_test:
            print("Checking if learning goals were achieved")
            check_learning_achieved(results, args.stop_reward)

    ray.shutdown()
