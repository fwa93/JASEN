import json
import logging

import click
from pydantic import ValidationError

from .models.metadata import RunInformation, SoupVersion
from .models.phenotype import PhenotypeType
from .models.qc import QcMethodIndex
from .models.sample import MethodIndex, PipelineResult
from .parse import (
    parse_cgmlst_results,
    parse_mlst_results,
    parse_quast_results,
    parse_resistance_pred,
    parse_kraken_result,
    parse_virulence_pred,
)

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
)
LOG = logging.getLogger(__name__)

OUTPUT_SCHEMA_VERSION = 1


@click.group()
def cli():
    pass


@cli.command()
@click.option("-i", "--sample-id", required=True, help="Sample identifier")
@click.option(
    "-u",
    "--run-metadata",
    type=click.File(),
    required=True,
    help="Analysis metadata from the pipeline in json format",
)
@click.option("-q", "--quast", type=click.File(), help="Quast quality control metrics")
@click.option(
    "-p",
    "--process-metadata",
    type=click.File(),
    multiple=True,
    help="Nextflow processes metadata from the pipeline in json format",
)
@click.option(
    "-k", "--kraken", type=click.File(), help="Kraken specie annotation results"
)
@click.option("-m", "--mlst", type=click.File(), help="MLST prediction results")
@click.option("-c", "--cgmlst", type=click.File(), help="cgMLST prediction results")
@click.option(
    "-v", "--virulence", type=click.File(), help="Virulence factor prediction results"
)
@click.option(
    "-r", "--resistance", type=click.File(), help="Resistance prediction results"
)
@click.argument("output", type=click.File("w"))
def create_output(
    sample_id,
    run_metadata,
    quast,
    process_metadata,
    kraken,
    mlst,
    cgmlst,
    virulence,
    resistance,
    output,
):
    """Combine pipeline results into a standardized json output file."""
    # base results
    LOG.info("Start generating pipeline result json")

    run_info = RunInformation(**json.load(run_metadata))
    results = {
        "sample_id": sample_id,
        "run_metadata": {"run": run_info},
        "qc": [],
        "typing_result": [],
        "phenotype_result": [],
    }
    if process_metadata:
        db_info: List[SoupVersion] = []
        for soup in process_metadata:
            dbs = json.load(soup)
            if isinstance(dbs, (list, tuple)):
                for db in dbs:
                    db_info.append(SoupVersion(**db))
            else:
                db_info.append(SoupVersion(**dbs))
        results["run_metadata"]["databases"] = db_info

    if quast:
        res: QcMethodIndex = parse_quast_results(quast)
        results["qc"].append(res)
    # typing
    if mlst:
        res: MethodIndex = parse_mlst_results(mlst)
        results["typing_result"].append(res)
    if cgmlst:
        res: MethodIndex = parse_cgmlst_results(cgmlst)
        results["typing_result"].append(res)

    # resistance of different types
    if resistance:
        pred_res = json.load(resistance)
        amr: MethodIndex = parse_resistance_pred(pred_res, PhenotypeType.AMR)
        chem: MethodIndex = parse_resistance_pred(pred_res, PhenotypeType.CHEM)
        env: MethodIndex = parse_resistance_pred(pred_res, PhenotypeType.ENV)
        results["phenotype_result"].extend([amr, chem, env])
    # get virulence factors in sample
    if virulence:
        vir: MethodIndex = parse_virulence_pred(virulence)
        results["phenotype_result"].append(vir)

    if kraken:
        LOG.info("Parse kraken results")
        results["species_prediction"] = parse_kraken_result(kraken)
    else:
        results["species_prediction"] = []

    try:
        output_data = PipelineResult(schema_version=OUTPUT_SCHEMA_VERSION, **results)
    except ValidationError as err:
        click.secho("Input failed Validation", fg="red")
        click.secho(err)
        raise click.Abort
    LOG.info(f"Storing results to: {output.name}")
    output.write(output_data.json(indent=2))
    click.secho("Finished generating pipeline output", fg="green")


@cli.command()
@click.argument("output", type=click.File("w"), default="-")
def print_schema(output):
    """Print Pipeline result output format schema."""
    click.secho(PipelineResult.schema_json(indent=2))


@cli.command()
@click.argument("output", type=click.File("r"))
def validate(output):
    """Validate output format of result json file."""
    js = json.load(output)
    try:
        PipelineResult(**js)
    except ValidationError as err:
        click.secho("Invalid file format X", fg="red")
        click.secho(err)
    else:
        click.secho(f'The file "{output.name}" is valid', fg="green")
