import sys
import json
import os
import logging
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    logging.getLogger("boto3").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.ERROR)
    logging.getLogger("sagemaker").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    import boto3
    import sagemaker
    from sagemaker.workflow.pipeline import Pipeline
    from sagemaker.workflow.steps import ProcessingStep, TrainingStep
    from sagemaker.workflow.lambda_step import LambdaStep
    from sagemaker.workflow.condition_step import ConditionStep
    from sagemaker.workflow.conditions import ConditionEquals
    from sagemaker.workflow.parameters import ParameterString, ParameterFloat
    from sagemaker.processing import ScriptProcessor, ProcessingInput, ProcessingOutput
    from sagemaker.sklearn.processing import SKLearnProcessor
    from sagemaker.estimator import Estimator
    from sagemaker.inputs import TrainingInput
    from sagemaker.lambda_helper import Lambda
    from sagemaker.workflow.properties import PropertyFile
    from sagemaker.workflow.functions import JsonGet
    from sagemaker.workflow.step_collections import RegisterModel

    try:
        role_arn = sys.argv[1]
        bucket_name = sys.argv[2]
        deploy_lambda_arn = sys.argv[3]
        project_name = sys.argv[4]
        mlflow_uri = sys.argv[5]
        training_image = sys.argv[6]
        source_dir_path = sys.argv[7]

        region = os.environ.get("AWS_DEFAULT_REGION", "eu-north-1")
    except IndexError:
        pass

    base_uri = f"s3://{bucket_name}"
    input_data = ParameterString(name="InputData", default_value=f"{base_uri}/datasets/real_estate/real_estate.csv")
    rmse_threshold = ParameterFloat(name="RmseThreshold", default_value=10.0)

    boto_session = boto3.Session(region_name=region)
    sagemaker_session = sagemaker.Session(boto_session=boto_session, default_bucket=bucket_name)
    LOCAL_SCRIPT_PATH = "../mlops_pipeline/scripts"

    # --- 1. PREPROCESSING ---
    sklearn_processor = SKLearnProcessor(
        framework_version="1.2-1",
        role=role_arn,
        instance_type="ml.t3.medium",
        instance_count=1,
        sagemaker_session=sagemaker_session,
        env={"MLFLOW_TRACKING_URI": mlflow_uri}
    )

    step_process = ProcessingStep(
        name="PreprocessData",
        processor=sklearn_processor,
        inputs=[ProcessingInput(source=input_data, destination="/opt/ml/processing/input")],
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(output_name="test", source="/opt/ml/processing/test")
        ],
        code=f"{LOCAL_SCRIPT_PATH}/preprocess.py",
    )

    # --- 2. TRAINING ---
    estimator = Estimator(
        image_uri=training_image,
        role=role_arn,
        instance_count=1,
        instance_type="ml.m5.large",
        output_path=f"{base_uri}/training_output",
        sagemaker_session=sagemaker_session,
        source_dir=source_dir_path,
        entry_point="train.py",
        environment={
            "MLFLOW_TRACKING_URI": mlflow_uri,
            "MLFLOW_EXPERIMENT_NAME": f"RealEstate-Pipeline-{project_name}"
        }
    )

    step_train = TrainingStep(
        name="TrainModel",
        estimator=estimator,
        inputs={
            "train": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri,
                content_type="text/csv"
            )
        }
    )

    # --- 3. EVALUATION ---
    script_eval = ScriptProcessor(
        image_uri=training_image,
        command=["python3"],
        role=role_arn,
        instance_type="ml.t3.medium",
        instance_count=1,
        sagemaker_session=sagemaker_session,
        env={"MLFLOW_TRACKING_URI": mlflow_uri}
    )

    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json"
    )

    step_eval = ProcessingStep(
        name="EvaluateModel",
        processor=script_eval,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model"
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs["test"].S3Output.S3Uri,
                destination="/opt/ml/processing/test"
            )
        ],
        outputs=[ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/evaluation")],
        code=f"{LOCAL_SCRIPT_PATH}/evaluate.py",
        property_files=[evaluation_report],
    )

    # --- 4. REGISTER MODEL ---
    step_register = RegisterModel(
        name="RegisterModel",
        estimator=estimator,
        model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["text/csv"],
        response_types=["text/csv"],
        inference_instances=["ml.m5.large"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=f"RealEstateModelGroup-{project_name}",
        approval_status="Approved",

        depends_on=[step_eval]
    )

    # --- 5. PROMOTION ---
    step_promote = ProcessingStep(
        name="PromoteModelInMLflow",
        processor=script_eval,
        code=f"{LOCAL_SCRIPT_PATH}/promote.py",
        depends_on=[step_register]
    )

    # --- 6. DEPLOY ---
    lambda_deploy = Lambda(function_arn=deploy_lambda_arn)

    step_deploy = LambdaStep(
        name="DeployToSageMaker",
        lambda_func=lambda_deploy,
        inputs={
            "model_package_arn": step_register.properties.ModelPackageArn,
            "endpoint_name": f"real-estate-endpoint-{project_name}",
            "role_arn": role_arn
        }
    )

    # --- 7. CONDITION ---
    cond_lte = ConditionEquals(
        left=JsonGet(
            step_name=step_eval.name,
            property_file=evaluation_report,
            json_path="metrics.is_better.value"
        ),
        right=1.0
    )

    step_cond = ConditionStep(
        name="CheckBetterThanProd",
        conditions=[cond_lte],
        if_steps=[step_register, step_deploy, step_promote],
        else_steps=[]
    )

    # --- PACKAGING ---
    pipeline = Pipeline(
        name=f"RealEstatePipeline-{project_name}",
        parameters=[input_data, rmse_threshold],
        steps=[step_process, step_train, step_eval, step_cond],
        sagemaker_session=sagemaker_session
    )

    definition = pipeline.definition()

try:
    print(json.dumps({"definition": definition}))
except Exception as e:
    sys.stderr.write(f"Error printing definition: {e}\n")
    sys.exit(1)